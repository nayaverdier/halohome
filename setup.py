from pathlib import Path

from setuptools import setup

ROOT_DIRECTORY = Path(__file__).resolve().parent

description = "A python library to control Eaton HALO Home Smart Lights"
readme = (ROOT_DIRECTORY / "README.md").read_text()
changelog = (ROOT_DIRECTORY / "CHANGELOG.md").read_text()
long_description = readme + "\n\n" + changelog

DEV_REQUIRES = [
    "black==23.3.0",
    "flake8==5.0.4",
    "flake8-bugbear==23.3.12",
    "isort==5.11.5",
    "twine==4.0.2",
    "wheel==0.42.0",
]

setup(
    name="halohome",
    version="0.7.0",
    description=description,
    long_description=long_description,
    long_description_content_type="text/markdown",
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
    ],
    author="Naya Verdier",
    url="https://github.com/nayaverdier/halohome",
    license="MIT",
    packages=["halohome"],
    install_requires=[
        "aiohttp~=3.7",
        "bleak~=0.13",
        "csrmesh~=0.10",
    ],
    python_requires=">=3.7",
    extras_require={
        "dev": DEV_REQUIRES,
    },
    include_package_data=True,
)
