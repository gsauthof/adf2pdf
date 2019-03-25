# cf. https://github.com/pypa/sampleproject/blob/master/setup.py

from setuptools import setup, find_packages
from codecs import open
from os import path
from adf2pdf import __version__

here = path.abspath(path.dirname(__file__))

with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

# Arguments marked as "Required" below must be included for upload to PyPI.
# Fields marked as "Optional" may be commented out.

setup(
    name='adf2pdf',  # Required
    version=__version__,  # Required
    description='Automate the workflow around ADF scanning, OCR and PDF creation',  # Required
    long_description=long_description,  # Optional
    long_description_content_type='text/markdown',  # Required with markdown
    url='https://github.com/gsauthof/adf2pdf',  # Optional
    author='Georg Sauthoff',  # Optional
    author_email='mail@gms.tf',  # Optional
    # https://pypi.org/classifiers/
    classifiers=[  # Optional
        # How mature is this project? Common values are
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        'Development Status :: 5 - Production/Stable',

        # Indicate who your project is intended for
        'Intended Audience :: End Users/Desktop',
        'Topic :: Multimedia :: Graphics :: Capture :: Scanners',

        # Pick your license as you wish
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',

        # Specify the Python versions you support here. In particular, ensure
        # that you indicate whether you support Python 2, Python 3 or both.
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],

    # This field adds keywords for your project which will appear on the
    # project page. What does your project relate to?
    #
    # Note that this is a string of words separated by whitespace, not a list.
    keywords='adf scanning sane duplex-scanning ocr tesseract pdf',  # Optional

    # You can just specify package directories manually here if your project is
    # simple. Or you can use find_packages().
    #
    # Alternatively, if you just want to distribute a single Python file, use
    # the `py_modules` argument instead as follows, which will expect a file
    # called `my_module.py` to exist:
    #
    #   py_modules=["my_module"],
    #
    #packages=find_packages(exclude=['contrib', 'docs', 'tests']),  # Required
    py_modules=['adf2pdf'],

    install_requires=['configargparse', 'img2pdf', 'Pillow', 'PyPDF2' ],  # Optional

    python_requires='>=3',

    entry_points={  # Optional
        'console_scripts': [
            'adf2pdf=adf2pdf:main',
        ],
    },

    project_urls={  # Optional
        'Bug Reports': 'https://github.com/gsauthof/adf2pdf/issues',
        'Say Thanks!': 'https://gms.tf',
        'Source': 'https://github.com/gsauthof/adf2pdf',
    },
)
