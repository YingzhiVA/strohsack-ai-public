"""
Strohsack AI - Setup Configuration
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="strohsack-ai",
    version="0.2.0",
    author="Yingzhi Vilimelis Aceituno",
    author_email="yingzhima.ch@gmail.com",
    description="An AI-powered conversational agent embodying a beloved plush bear's personality",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/YingzhiVA/strohsack-ai",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    package_data={"strohsack": ["personality/*.txt"]},
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.10",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "pytest-cov>=4.1.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.5.0",
        ],
    },
)
