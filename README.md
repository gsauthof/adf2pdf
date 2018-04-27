This repository contains **adf2pdf**, a tool that turns paper
documents into PDFs with a text layer. For that, it calls
external programs to do the different subtasks: for example,
[Sane's][5] [scanimage][6] for the scanning, ImageMagick for
empty page detection and [Tesseract][4] for the [optical character
recognition] (OCR). By default, it detects empty pages (as they may easily
occur during duplex scanning) and excludes them from the OCR and
the resulting PDF.

Example:

    $ ./adf2pdf.py contract-xyz.pdf

2017, Georg Sauthoff <mail@gms.tf>

## Hardware Requirements

A scanner with automatic document feed (ADF) that is supported by
`scanadf`. For example, the [Fujitsu ScanSnap S1500][1] works
well. That model supports duplex scanning, which is quite
convenient.

## Software Requirements

The script assumes Tesseract version 4, by default. Version 3 can
be used as well, but the [new neural network system in Tesseract
4][8] just performs magnitudes better than the old OCR model.
As of late 2017, there is no stable version 4, yet, but since
the alpha version is so much better at OCR I can't recommend it
enough over the stable version 3.

Tesseract 4 notes:

- [Build instructions][2] - warning: if you miss the
  `autoconf-archive` dependency you'll get weird autoconf error
  messages
- [Data files][3] - you need the training data for your
  languages of choice and the OSD data


[1]: http://www.fujitsu.com/us/products/computing/peripheral/scanners/product/eol/s1500/
[2]: https://github.com/tesseract-ocr/tesseract/wiki/Compiling-–-GitInstallation
[3]: https://github.com/tesseract-ocr/tesseract/wiki/Data-Files
[4]: https://en.wikipedia.org/wiki/Tesseract_(software)
[5]: https://en.wikipedia.org/wiki/Scanner_Access_Now_Easy
[6]: http://www.sane-project.org/man/scanimage.1.html
[7]: https://en.wikipedia.org/wiki/Optical_character_recognition
[8]: https://github.com/tesseract-ocr/tesseract/wiki/NeuralNetsInTesseract4.00
