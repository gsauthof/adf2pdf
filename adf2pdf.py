#!/usr/bin/env python3

# adf2pdf - automate the workflow around scanadf and tesseract.
#
# 2017, Georg Sauthoff <mail@gms.tf>, GPLv3+

import configargparse
import contextlib
from distutils.version import LooseVersion
import glob
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import multiprocessing


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
      help='Work directory (default: automatically created under --temp value)')
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
  if args.log:
    setup_file_logging(args.log)
  if not args.debug:
    logging.getLogger().handlers[0].setLevel(logging.WARNING)
  args.output = os.path.abspath(args.output[0])
  if not args.j:
    args.j = max(multiprocessing.cpu_count() - 1, 1)
    log.debug('Starting {} convert jobs at most'.format(args.j))
  if args.output.endswith('.pdf'):
    args.output = args.output[:-4]
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
  pat = 'image-%04d'
  if args.color:
    mode   = 'Color'
    format = 'jpeg'
    pat   += '.jpg'
  else:
    mode   = 'Lineart'
    format = 'png'
    pat   += '.png'
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
        except subprocess.TimeoutExpired:
          yield (None, xs, None, None, None)


def imain(args):
  if check_tesseract(args):
    log.error('Tesseract is too old. Try putting Tesseract 4 into the PATH.')
    return 1
  with Temporary_Directory(name=args.work,
      dir=args.temp, delete=args.keep_work) as args.work:
    return imain_rest(args)

def imain_rest(args):
  tesseract = Popen(['tesseract', '--oem', args.oem, '-l', args.lang,
      '-c', 'stream_filelist=true', '-', args.output, 'pdf'],
      stdin=subprocess.PIPE,
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL)
  pool = PQueue(args.j)
  def forward_page(p, xs, ys, o, e):
    if p:
      if xs[1] in args.exclude:
        log.debug('Ignoring {}. page because it is excluded'.format(xs[1]))
      elif is_empty_img(o):
        log.warn('Ignoring {}. page because it is empty'.format(xs[1]))
      else:
        log.debug('Sending {} to tesseract'.format(xs[0]))
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
    for p, xs, ys, o, e in pool.yield_done(timeout=0):
      if not forward_page(p, xs, ys, o, e):
        break
  for p, xs, ys, o, e in pool.yield_done():
    forward_page(p, xs, ys, o, e)
  log.debug('Closing tesseract stdin')
  tesseract.stdin.close()
  log.debug('Waiting on tesseract')
  tesseract.wait()
  return 0

def main(*a):
  setup_logging()
  args = parse_args(*a)
  return imain(args)

if __name__ == '__main__':
  sys.exit(main())
