#!/usr/bin/env python

from setuptools import setup, find_packages
from cassandra_snapshotter import __version__, __maintainer__, __email__


install_requires = [
    'argparse',
    'fabric',
    'boto>=2.29.1'
]

setup(
    name='cassandra_snapshotter',
    version=__version__,
    author=__maintainer__,
    author_email=__email__,
    url='http://github.com/tbarbugli/cassandra_snapshotter',
    description='Cassandra snapshotter is a tool to backup cassandra to Amazon S3.',
    packages=find_packages(),
    zip_safe=False,
    install_requires=install_requires,
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'cassandra-snapshotter = cassandra_snapshotter.main:main',
            'cassandra-snapshotter-agent = cassandra_snapshotter.agent:main'
        ]
    },
    classifiers=[
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Operating System :: OS Independent',
        'Topic :: Software Development',
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: GNU General Public License (GPL)',
        'Natural Language :: English',
        'Programming Language :: Python',
        'Topic :: Scientific/Engineering :: Mathematics',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ],
)
