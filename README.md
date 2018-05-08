adf2pdf - a tool that turns a batch of paper pages into a PDF
with a text layer.  By default, it detects empty pages (as they
may easily occur during duplex scanning) and excludes them from
the OCR and the resulting PDF.

For that, it uses [Sane's][5] [scanimage][6] for the scanning,
[Tesseract][4] for the [optical character recognition] (OCR), and
the Python packages [img2pdf][9], [Pillow (PIL)][10] and
[PyPDF2][11] for some image-processing tasks and PDF mangling.


Example:

    $ adf2pdf contract-xyz.pdf

2017, Georg Sauthoff <mail@gms.tf>

## Features

- Automatic document feed (ADF) support
- Fast empty page detection
- Overlaying of scanning, image processing, OCR and PDF creation
  to minimize the total runtime
- Fast creation of small PDFs using the fine [img2pdf][9] package
- Only use of safe compression methods, i.e. no error-prone
  symbol segmentation style compression like [JBIG2][12] or JB2
  that is used in [Xerox photocopiers][12] and the DjVu format.

## Install Instructions

Adf2pdf can be directly installed with [`pip`][13], e.g.

    $ pip3 install --user adf2pdf

or

    $ pip3 install adf2pdf

See also the [PyPI adf2pdf project page][14].

Alternatively, the Python file `adf2pdf.py` can be directly
executed in a cloned repository, e.g.:

    $ ./adf2pdf.py report.pdf

In addition to that, one can install the development version from
a cloned work-tree like this:

    $ pip3 install --user .

## Hardware Requirements

A scanner with automatic document feed (ADF) that is supported by
Sane. For example, the [Fujitsu ScanSnap S1500][1] works
well. That model supports duplex scanning, which is quite
convenient.

## Example continued

Running _adf2pdf_ for a 7 page example document takes 150 seconds
on an i7-6600U (Intel Skylake, 4 cores) CPU (using the ADF of the
Fujitsu ScanSnap S1500). With the defaults, _adf2pdf_ calls
`scanimage` for duplex scanning into 600 dpi lineart (black and
white) images. In this example, 6 pages are empty and thus
automatically excluded, i.e. the resulting PDF then just contains
8 pages.

The resulting PDF contains a text layer from the OCR such that
one can search and copy'n'paste some text. It is 1.1 MiB big,
i.e. a page is stored in 132 KiB, on average.

## Software Requirements

The script assumes Tesseract version 4, by default. Version 3 can
be used as well, but the [new neural network system in Tesseract
4][8] just performs magnitudes better than the old OCR model.
As of mid 2018, there is no stable version 4, yet, but since
the beta version is so much better at OCR I can't recommend it
enough over the stable version 3.

Tesseract 4 notes:

- [Build instructions][2] - warning: if you miss the
  `autoconf-archive` dependency you'll get weird autoconf error
  messages
- [Data files][3] - you need the training data for your
  languages of choice and the OSD data

Python packages:

- [img2pdf][9] (not packaged for Fedora, yet) - version 0.2.4 works
  fine
- [Pillow (PIL)][10] (Fedora package: python3-pillow-devel)
- [PyPDF2][11] (Fedora package: python3-PyPDF2)

[1]: http://www.fujitsu.com/us/products/computing/peripheral/scanners/product/eol/s1500/
[2]: https://github.com/tesseract-ocr/tesseract/wiki/Compiling-–-GitInstallation
[3]: https://github.com/tesseract-ocr/tesseract/wiki/Data-Files
[4]: https://en.wikipedia.org/wiki/Tesseract_(software)
[5]: https://en.wikipedia.org/wiki/Scanner_Access_Now_Easy
[6]: http://www.sane-project.org/man/scanimage.1.html
[7]: https://en.wikipedia.org/wiki/Optical_character_recognition
[8]: https://github.com/tesseract-ocr/tesseract/wiki/NeuralNetsInTesseract4.00
[9]: https://pypi.org/project/img2pdf/
[10]: http://python-pillow.github.io/
[11]: https://github.com/mstamy2/PyPDF2
[12]: https://en.wikipedia.org/wiki/JBIG2
[13]: https://en.wikipedia.org/wiki/Pip_(package_manager)
[14]: https://pypi.org/project/adf2pdf/
