from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="simplecontext",
    version="3.0.0",
    description="Universal AI Brain — Zero Touch, Zero Dependencies.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/zacxyonly/SimpleContext",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[],
    extras_require={
        "redis":    ["redis>=5.0"],
        "postgres": ["psycopg2-binary>=2.9"],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
