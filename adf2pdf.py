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
import os
import PIL.Image
import PIL.ImageFilter
import PIL.ImageStat
import PyPDF2
import re
import shutil
import subprocess
import sys
import tempfile

__version__ = '0.8.1'

def mk_arg_parser():
  p = configargparse.ArgumentParser(
      default_config_files=['/etc/adf2pdf.conf', '~/.config/adf2pdf.conf'],
      formatter_class=configargparse.RawDescriptionHelpFormatter,
      description='Auto-feed documents into PDFs with a text layer.',
      epilog='''That means this tool automates the workflow around scanadf
and tesseract. It's recommended to use Tesseract 4, for better OCR
performance - even if only the beta version is available.

2017-2018, Georg Sauthoff <mail@gms.tf>, GPLv3+
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
  p.add_argument('--text', '--txt', '-t', action='store_true',
      help='Also generate a .txt file. This usually yields a better structured text file than just creating a PDF and using pdftotext on it')
  p.add_argument('--resolution', type=int, default=600,
          help='Scan resolution (default: 600 dpi)')
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
  if args.output.lower().endswith('.pdf'):
    args.output_txt = args.output[:-3] + 'txt'
  else:
    args.output_txt = args.output + '.txt'
  if args.log:
    setup_file_logging(args.log)
  if not args.debug:
    logging.getLogger().handlers[0].setLevel(logging.WARNING)
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
  return subprocess.Popen(cmd, *xs, **ys)

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
      '--page-width=210', '--page-height=297',
      '--resolution={}'.format(args.resolution)
      ] + duplex + [
      '--mode=' + mode,
      '--format=' + format,
      '--batch={}/{}'.format(args.work, pat),
      '--batch-print'],
      universal_newlines=True,
      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as p:
    for line in p.stdout:
      yield line[:-1]

def avg_brightness(filename, args):
  margin = int(args.resolution * 0.7)
  img = PIL.Image.open(filename)
  log.debug('Dimensions (W x H): {}'.format(img.size))
  img = img.convert('L')
  # exclude the margins to ignore punch holes etc.
  img = img.crop((margin, margin, img.size[0] - margin, img.size[1] - margin))
  stat = PIL.ImageStat.Stat(img)
  # shifting the mean to deal with empty pages where the
  # reverse page shines through a little
  m = stat.mean[0] - 50
  log.debug('Image avg brightness of {}: {}'.format(filename, m))
  log.debug('Image rms brightness of {}: {}'.format(filename, stat.rms[0]))
  return img, m

def binarize(input_img, thresh):
  # with grayscale, 0 is black and 255 is white (bightest)
  # to simplify the counting we binarize to: 0=white, 1=black
  img = input_img.point(lambda v : v < thresh)
  return img

def erode(input_img):
  # alternative value: 3
  img = input_img.filter(PIL.ImageFilter.MinFilter(5))
  return img

def count_black_px(img):
  n = img.size[0] * img.size[1]
  x = sum(img.getdata())
  log.debug('{} of {} pixels are black ({:.2f} %)'.format(x, n, x/n*100))
  return x

# cf. https://dsp.stackexchange.com/a/48837/35404
def is_empty(filename, args):
  img, thresh = avg_brightness(filename, args)
  img = binarize(img, thresh)
  img = erode(img)
  x = count_black_px(img)
  return x < 100



def check_tesseract(args):
  o = subprocess.check_output(['tesseract', '--version'],
      universal_newlines=True)
  ls = o.splitlines()
  _, version = ls[0].split()
  return LooseVersion(version) < LooseVersion('4') \
      and not args.old_tesseract


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
  filename = args.work + '/image-only.pdf' if args.ocr else args.output
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
  create_txt = ['-c', 'tessedit_create_txt=1' ] if args.text else []
  tesseract = Popen(['tesseract', '--oem', args.oem, '-l', args.lang,
      '-c', 'stream_filelist=true',
      '-c', 'textonly_pdf=1',
      '-c', 'tessedit_create_pdf=1',
      ] + create_txt + [
      '-', args.work + '/text-only' ],
      universal_newlines=True,
      bufsize=1, # enable line buffering, requires universal_newlines=True
      stdin=subprocess.PIPE,
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL) if args.ocr else None
  imgs = []
  for i, filename in enumerate(scanadf(args), 1):
    log.debug('{} successfully scanned'.format(filename))
    if not args.keep_empty:
      if i in args.exclude:
        log.debug('Ignoring {}. page because it is excluded'.format(i))
        continue
      if is_empty(filename, args):
        log.warning('Ignoring {}. page because it is empty'.format(i))
        continue
    imgs.append(filename)
    if args.ocr:
      log.debug('Sending {} to tesseract'.format(filename))
      tesseract.stdin.write(filename + '\n')
  if args.ocr:
    log.debug('Closing tesseract stdin')
    tesseract.stdin.close()
  if not imgs:
    log.error('No images retrieved.')
    return 1
  create_img_pdf(imgs, args)
  if args.ocr:
    log.debug('Waiting on tesseract')
    tesseract.wait()
    # merge images on top of text or the other way around
    # cf. https://github.com/tesseract-ocr/tesseract/issues/660#issuecomment-273389307
    merge_pdfs(args.work + '/text-only.pdf',  args.work + '/image-only.pdf',
          args.output)
  if args.text:
    log.debug('Creating text file: {}'.format(args.output_txt))
    shutil.copy(args.work + '/text-only.txt', args.output_txt)
  return 0

def main(*a):
  setup_logging()
  args = parse_args(*a)
  return imain(args)

if __name__ == '__main__':
  sys.exit(main())
