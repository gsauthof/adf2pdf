#!/usr/bin/env python3

# adf2pdf - automate the workflow around scanadf and tesseract.
#
# 2017, Georg Sauthoff <mail@gms.tf>, GPLv3+

import configargparse
from distutils.version import LooseVersion
import glob
import logging
import os
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
      help='language for OCR (default: deu)')
  p.add_argument('--work', metavar='DIRECTORY',
      help='work directory')
  p.add_argument('--log', metavar='FILENAME', const='debug.log', nargs='?',
      help='also write log messages into a file')
  p.add_argument('--keep-empty', action='store_true',
      help='keep empty pages')
  p.add_argument('--keep-work', action='store_true',
      help='keep the work directory')
  p.add_argument('--debug', '-v', action='store_true',
      help='print debug messages to the console')
  p.add_argument('--oem', default='1',
      help='tesseract model (0=legacy, 1=neural) (default: 1)')
  p.add_argument('--no-scan', action='store_true',
      help='assume that work directory already contains the image files')
  p.add_argument('--color', action='store_true',
      help='scan with colors')
  p.add_argument('--device', '-d', default='fujitsu:ScanSnap S1500:53095',
      help='Scanner device')
  p.add_argument('--old-tesseract', action='store_true',
      help='Allow Tesseract version < 4')
  return p

def parse_args(*a):
  arg_parser = mk_arg_parser()
  args = arg_parser.parse_args(*a)
  if args.log:
    setup_file_logging(args.log)
  if not args.debug:
    logging.getLogger().handlers[0].setLevel(logging.WARNING)
  args.output = os.path.abspath(args.output[0])
  if not args.work:
    p = '/var/tmp'
    if os.path.exists(p):
      args.work = tempfile.mkdtemp(dir=p)
    else:
      args.work = tempfile.mkdtemp()
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

def run(cmd, *xs, **ys):
  call = ' '.join(quote_arg(x) for x in cmd)
  log.debug('Calling: ' + call)
  try:
    r = subprocess.run(cmd, *xs, **ys)
  except subprocess.CalledProcessError as e:
    log.error(('Command exited with: {}\n'
        'Call: {}\n    Stdout: {}\n    Stderr: {}')
        .format(e.returncode, call, e.stdout, e.stderr))
    raise
  log.debug(('Command exited with: {}\n'
      'Call: {}\n    Stdout: {}\n    Stderr: {}')
      .format(r.returncode, call, r.stdout, r.stderr))
  return r

def runo(cmd, *xs, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, universal_newlines=True, **ys):
  return run(cmd, *xs, stdout=stdout, stderr=stderr, check=check, universal_newlines=universal_newlines, **ys)

def scanadf(args):
  mode = 'Color' if args.color else 'Lineart'
  runo(['scanadf', '-d', args.device,
      '--page-width=210', '--page-height=297', '--resolution=600',
      '--source=ADF Duplex', '--mode=' + mode,
      '-v', '-N', '-s1', '-o', 'image-%04d'])

def convert_img(args, filename):
  ext = '.jpg' if args.color else '.png'
  output = filename + ext
  runo(['convert', filename, '-density', '600', '-units', 'pixelsperinch',
    output])
  return output

def create_filelist(xs, filename):
  with open(filename, 'w') as f:
    for x in xs:
      print(x, file=f)

def create_pdf(args, images, filenameP):
  filename = filenameP[:-4] if filenameP.endswith('.pdf') else filenameP
  create_filelist(images, 'tlist')
  runo(['tesseract', '--oem', args.oem, '-l', args.lang, 'tlist',
      filename, 'pdf'])

dim_re = re.compile('(PNG|JPEG) ([0-9]+)x([0-9]+) ')

def is_empty_img(filename):
  # doing a noisy trim here - cf.
  # http://www.imagemagick.org/Usage/crop/#trim_blur
  # http://www.imagemagick.org/Usage/compare/ (Blank Fax)
  # '-virtual-pixel', 'edge'
  r = runo(['convert', filename, '-shave', '300x0',
    '-virtual-pixel', 'White', '-blur', '0x15',
    '-fuzz', '15%', '-trim', 'info:'])
  m = dim_re.search(r.stdout)
  if not m:
    raise  RuntimeError("Couldn't find dimensions in: {}".format(r.stdout))
  return int(m.group(2)) < 80 or int(m.group(3)) < 80
  #return 'geometry does not contain image' in r.stderr

def check_tesseract(args):
  o = runo(['tesseract', '--version'])
  ls = o.stdout.splitlines()
  _, version = ls[0].split()
  return LooseVersion(version) < LooseVersion('4') \
      and not args.old_tesseract

def imain(args):
  if check_tesseract(args):
    log.error('Tesseract is too old. Try putting Tesseract 4 into the PATH.')
    return 1
  log.debug('Changing to workdir: {}'.format(args.work))
  os.makedirs(args.work, exist_ok=True)
  os.chdir(args.work)
  if not args.no_scan:
    scanadf(args)
  xs = []
  for i, filename in enumerate(
      sorted(glob.glob('image-[0-9][0-9][0-9][0-9]')), 1):
    x = convert_img(args, filename)
    if not args.keep_empty and is_empty_img(x):
      log.warn('Ignoring {}. page because it is empty'.format(i))
    else:
      xs.append(x)
  if not xs:
    raise RuntimeError('No images to convert ...')
  create_pdf(args, xs, args.output)
  if not args.keep_work:
    log.debug('Removing workdir: {}'.format(args.work))
    shutil.rmtree(args.work)

  return 0

def main(*a):
  setup_logging()
  args = parse_args(*a)
  return imain(args)

if __name__ == '__main__':
  sys.exit(main())
