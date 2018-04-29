#!/usr/bin/env python3

# adf2pdf - obtain images from an automatic document feed scanner,
#           exclude empty pages, apply OCR and create a nice
#           (i.e. small and high-quality) PDF with a text layer
#
# 2017, Georg Sauthoff <mail@gms.tf>, GPLv3+

import configargparse
import contextlib
from distutils.version import LooseVersion
import glob
import img2pdf # 0.2.4 works fine
import logging
import multiprocessing
import os
import PIL
import PyPDF2
import re
import shutil
import subprocess
import sys
import tempfile


def mk_arg_parser():
  p = configargparse.ArgumentParser(
      default_config_files=['/etc/adf2pdf.conf', '~/.config/adf2pdf.conf'],
      formatter_class=configargparse.RawDescriptionHelpFormatter,
      description='Auto-feed documents into PDFs with a text layer.',
      epilog='''That means this tool automates the workflow around scanadf
and tesseract. It's recommended to use Tesseract 4, for better OCR
performance - even if only the alpha version is available.

2017, Georg Sauthoff <mail@gms.tf>, GPLv3+
      ''')
  p.add('output', metavar='FILENAME', nargs=1,
      help='output PDF filename')
  p.add_argument('--lang', '-l', metavar='ISO3',
      default='deu',
      help='Language for OCR (default: deu)')
  p.add_argument('--work', metavar='DIRECTORY',
      help='Work directory (default: automatically created under --temp value). The complete work directory is deleted unless --keep-work is specified.')
  p.add_argument('--temp', metavar='DIRECTORY', default='/var/tmp',
      help='Temporary base directory (default: /var/tmp). Used unless --work is specified.')
  p.add_argument('--log', metavar='FILENAME', const='debug.log', nargs='?',
      help='Also write log messages into a file')
  p.add_argument('--keep-empty', action='store_true',
      help='Keep empty pages (i.e. disable empty page detection).')
  p.add_argument('--keep-work', action='store_true',
      help='Keep the work directory')
  p.add_argument('--debug', '-v', action='store_true',
      help='Print debug messages to the console')
  p.add_argument('--oem', default='1',
      help='Tesseract model (0=legacy, 1=neural) (default: 1)')
  p.add_argument('--no-scan', action='store_true',
      help='Assume that work directory already contains the image files')
  p.add_argument('--color', action='store_true',
      help='Scan with colors')
  p.add_argument('--device', '-d', default='fujitsu:ScanSnap S1500:53095',
      help='Scanner device')
  p.add_argument('--old-tesseract', action='store_true',
      help='Allow Tesseract version < 4')
  p.add_argument('-j', type=int,
      help='Number of parallel convert jobs to start (default: cores-1)')
  p.add_argument('--exclude', '-x', default='',
      help='Comma-separated list of pages to ignore')
  p.add_argument('--duplex', action='store_true', default=True,
      help='Scan front and back at once (default: true)')
  p.add_argument('--simplex', dest='duplex', action='store_false',
      help='Disable duplex scanning')
  p.add_argument('--jp2', action='store_true',
      help='Use the JPEG 2000 format instead of just JPEG when scanning in color (cf. --color)')
  p.add_argument('--png', action='store_true',
      help="When using --color, don't compress the images into JPEG before including them in the PDF (not recommended)")
  p.add_argument('--ocr', action='store_true', default=True,
      help='Enable OCR (via Tesseract) (default: true)')
  p.add_argument('--no-ocr', dest='ocr', action='store_false',
      help='Disable OCR')
  return p

@contextlib.contextmanager
def Temporary_Directory(name=None, suffix=None, prefix=None, dir=None, delete=True):
  if name:
    os.makedirs(name, exist_ok=True)
    dirname = name
  else:
    dirname = tempfile.mkdtemp(suffix, prefix, dir)
  try:
    yield dirname
  finally:
    if delete:
      log.debug('Removing temporary directory: {}'.format(dirname))
      shutil.rmtree(dirname)

def parse_args(*a):
  arg_parser = mk_arg_parser()
  args = arg_parser.parse_args(*a)
  args.output = args.output[0]
  if args.log:
    setup_file_logging(args.log)
  if not args.debug:
    logging.getLogger().handlers[0].setLevel(logging.WARNING)
  if not args.j:
    args.j = max(multiprocessing.cpu_count() - 1, 1)
    log.debug('Starting {} convert jobs at most'.format(args.j))
  if args.exclude:
    args.exclude = set(int(x) for x in args.exclude.split(','))
  else:
    args.exclude = set()
  return args

# Logging

log_format      = '{rel_secs:6.1f} {lvl}  {message}'
log_date_format = '%Y-%m-%d %H:%M:%S'

# handle for the module
log = logging.getLogger(__name__)


class Relative_Formatter(logging.Formatter):
  level_dict = { 10 : 'DBG',  20 : 'INF', 30 : 'WRN', 40 : 'ERR',
      50 : 'CRI' }
  def format(self, rec):
    rec.rel_secs = rec.relativeCreated/1000.0
    rec.lvl = self.level_dict[rec.levelno]
    return super(Relative_Formatter, self).format(rec)

def setup_logging():
  logging.basicConfig(format=log_format, datefmt=log_date_format,
      level=logging.DEBUG)
  logging.getLogger().handlers[0].setFormatter(
      Relative_Formatter(log_format, log_date_format, style='{'))

def setup_file_logging(filename):
  fh = logging.FileHandler(filename)
  fh.setLevel(logging.DEBUG)
  f = Relative_Formatter(log_format, log_date_format, style='{')
  fh.setFormatter(f)
  logging.getLogger().addHandler(fh)

def quote_arg(x):
  def need_quotes(x):
    meta_char = [ '|', '&', ';', '(', ')', '<', '>', ' ', '\t' ]
    other = [ "'", '"', '`', '$' ]
    for c in meta_char + other:
      if c in x:
        return True
    return False
  if need_quotes(x):
    r = x.replace("'", """'"'"'""")
    return "'" + r + "'"
  return x

def Popen(cmd, *xs, **ys):
  call = ' '.join(quote_arg(x) for x in cmd)
  log.debug('Calling: ' + call)
  return subprocess.Popen(cmd, *xs, universal_newlines=True, **ys)

def scanadf(args):
  format = 'png'
  pat    = 'image-%04d.png'
  mode   = 'Color' if args.color else 'Lineart'

  if args.no_scan:
    t = '{}/*{}'.format(args.work, pat.replace('%04d', '*'))
    log.debug('globbing for: {}'.format(t))
    yield from sorted(glob.glob(t))
    return

  duplex = [ '--source=ADF Duplex' ] if args.duplex else []
  with Popen(['scanimage', '-d', args.device,
      '--page-width=210', '--page-height=297', '--resolution=600'
      ] + duplex + [
      '--mode=' + mode,
      '--format=' + format,
      '--batch={}/{}'.format(args.work, pat),
      '--batch-print'],
      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as p:
    for line in p.stdout:
      yield line[:-1]


dim_re = re.compile('(PNG|JPEG) ([0-9]+)x([0-9]+) ')

def start_is_empty_img(filename, i):
  # doing a noisy trim here - cf.
  # http://www.imagemagick.org/Usage/crop/#trim_blur
  # http://www.imagemagick.org/Usage/compare/ (Blank Fax)
  # '-virtual-pixel', 'edge'
  p = Popen(['convert', filename, '-shave', '300x0',
      '-virtual-pixel', 'White', '-blur', '0x15',
      '-fuzz', '15%', '-trim', 'info:'],
      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
  return p

def is_empty_img(stdout):
  m = dim_re.search(stdout)
  if not m:
    raise  RuntimeError("Couldn't find dimensions in: {}".format(stdout))
  return int(m.group(2)) < 80 or int(m.group(3)) < 80
  #return 'geometry does not contain image' in r.stderr

def check_tesseract(args):
  o = subprocess.check_output(['tesseract', '--version'],
      universal_newlines=True)
  ls = o.splitlines()
  _, version = ls[0].split()
  return LooseVersion(version) < LooseVersion('4') \
      and not args.old_tesseract

class PQueue:
  def __init__(self, j):
    self._j = j
    self._running = []
    self._running_cnt = 0
    self._queued = []
    self._done = []
  def start(self, f, *xs, **ys):
    self._queued.append((f, xs, ys))
    self._start_more()
  def _start_more(self):
    while self._queued and self._running_cnt < self._j:
      f, xs, ys = self._queued.pop(0)
      p = f(*xs, **ys)
      self._running.append((p, xs, ys))
      if type(p) is subprocess.Popen:
        self._running_cnt += 1
  def yield_done(self, timeout=None):
    while self._done or self._running or self._queued:
      self._start_more()
      for p, xs, ys, o, e in self._done:
        yield (p, xs, ys, o, e)
      self._done.clear()
      if self._running:
        try:
          p, xs, ys = self._running[0]
          if type(p) is subprocess.Popen:
            o, e = p.communicate(timeout=timeout)
          else:
            o, e = p
          self._done.append((p, xs, ys, o, e))
          self._running.pop(0)
          self._running_cnt -= 1
        except subprocess.TimeoutExpired:
          yield (None, xs, None, None, None)

# One thing to keep in mind:
# scanimage supports directly writing jpg and tesseract supports doing
# OCR on jpg, but the lossy compression of jpg can only decrease
# the efficiency of the OCR. Thus, tesseract must always
# get its input lossless for optimal OCR results while colored
# images must be JPG compressed before going into the resulting PDF
# to save space.
def png2jpg(filename, ofilename):
  log.debug('Converting {} to {}'.format(filename, ofilename))
  if ofilename.endswith('.jpg'):
    opts = { 'optimize': True }
  else:
    opts = { 'quality_mode': 'rates', 'quality_layers': [70] }
  with PIL.Image.open(filename) as png:
    img = png.convert('RGB')
    img.save(ofilename, **opts)
  return ofilename

# img2pdf performs better than ImageMagick and Tesseract, i.e. the
# resulting PDF is much smaller for lineart PNG images and
# not bigger than the input for JPEG images. With 0.2.4 PNG
# images are losslessly re-encoded into CCITT, while the JPEGs
# are included as-is. Both ImageMagick and Tesseract don't
# use CCITT for the lineart PNGs and at least ImageMagick unnecessarily
# re-encodes the JPEGs, thus yielding larger and lower quality images.
# With lineart PNGs, the Tesseract image PDF is 1.5 times or so as big,
# while the ImageMagick PDF is 2 times or so as big.
# The img2pdf master branch contains some work for including PNGs as-is,
# as well - although, for this use-case CCITT seems to be better suited
# than the PNGs created by scanimage. (cf. pdfimages -list)
def create_img_pdf(imgs, args):
  filename = args.work + '/image-only.pdf'
  log.debug('Writing images to pdf: {}'.format(filename))
  if args.color and not args.png:
    jpg = 'jp2' if args.jp2 else 'jpg'
    ts = []
    for img in imgs:
      ts.append(png2jpg(img, img[:-3] + jpg))
    imgs = ts
  with open(filename, 'wb') as f:
    log.debug('Images: {}'.format(imgs))
    a4 = (img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297))
    layout_fn = img2pdf.get_layout_fun(a4)
    img2pdf.convert(imgs, outputstream=f, layout_fun=layout_fn)

# cf. https://github.com/tesseract-ocr/tesseract/issues/660#issuecomment-273629726
def merge_pdfs(filename1, filename2, ofilename):
  log.debug('Merging {} and {} into {}'.format(filename1, filename2, ofilename))
  with open(filename1, 'rb') as f1, open(filename2, 'rb') as f2:
    pdf1, pdf2 = (PyPDF2.PdfFileReader(x) for x in (f1, f2))
    opdf = PyPDF2.PdfFileWriter()
    for page1, page2 in zip(pdf1.pages, pdf2.pages):
      page1.mergePage(page2)
      opdf.addPage(page1)
    with open(ofilename, 'wb') as g:
      opdf.write(g)

def imain(args):
  if args.ocr and check_tesseract(args):
    log.error('Tesseract is too old. Try putting Tesseract 4 into the PATH.')
    return 1
  with Temporary_Directory(name=args.work,
      dir=args.temp, delete=(not args.keep_work)) as args.work:
    log.debug('Working under: {}'.format(args.work))
    return imain_rest(args)


def imain_rest(args):
  tesseract = Popen(['tesseract', '--oem', args.oem, '-l', args.lang,
      '-c', 'stream_filelist=true',
      '-c', 'textonly_pdf=1',
      '-', args.work + '/text-only', 'pdf'],
      stdin=subprocess.PIPE,
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL) if args.ocr else None
  pool = PQueue(args.j)
  imgs = []
  def forward_page(p, xs, ys, o, e):
    if p:
      if xs[1] in args.exclude:
        log.debug('Ignoring {}. page because it is excluded'.format(xs[1]))
      elif is_empty_img(o):
        log.warn('Ignoring {}. page because it is empty'.format(xs[1]))
      else:
        log.debug('Sending {} to tesseract'.format(xs[0]))
        imgs.append(xs[0])
        if args.ocr:
          tesseract.stdin.write(xs[0] + '\n')
    else:
      log.debug('Still waiting on is_empty process for {}'.format(xs[0]))
      return False
    return True
  for i, filename in enumerate(scanadf(args), 1):
    log.debug('{} successfully scanned'.format(filename))
    if args.keep_empty or i in args.exclude:
      pool.start(lambda x,y: ('PNG 2323x2323 ', None), filename, i)
    else:
      pool.start(start_is_empty_img, filename, i)
    for p, xs, ys, o, e in pool.yield_done(timeout=0.1):
      if not forward_page(p, xs, ys, o, e):
        break
  for p, xs, ys, o, e in pool.yield_done():
    forward_page(p, xs, ys, o, e)
  if args.ocr:
    log.debug('Closing tesseract stdin')
    tesseract.stdin.close()
  create_img_pdf(imgs, args)
  if args.ocr:
    log.debug('Waiting on tesseract')
    tesseract.wait()
  # merge images on top of text or the other way around
  # cf. https://github.com/tesseract-ocr/tesseract/issues/660#issuecomment-273389307
  merge_pdfs(args.work + '/text-only.pdf',  args.work + '/image-only.pdf',
      args.output)
  return 0

def main(*a):
  setup_logging()
  args = parse_args(*a)
  return imain(args)

if __name__ == '__main__':
  sys.exit(main())
