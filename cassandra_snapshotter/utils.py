import sys

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
import argparse
import functools
import subprocess

LZOP_BIN = 'lzop'
PV_BIN = 'pv'

S3_CONNECTION_HOSTS = {
    'us-east-1': 's3.amazonaws.com',
    'us-west-2': 's3-us-west-2.amazonaws.com',
    'us-west-1': 's3-us-west-1.amazonaws.com',
    'eu-central-1': 's3-eu-central-1.amazonaws.com',
    'eu-west-1': 's3-eu-west-1.amazonaws.com',
    'ap-southeast-1': 's3-ap-southeast-1.amazonaws.com',
    'ap-southeast-2': 's3-ap-southeast-2.amazonaws.com',
    'ap-northeast-1': 's3-ap-northeast-1.amazonaws.com',
    'sa-east-1': 's3-sa-east-1.amazonaws.com'
}

base_parser = argparse.ArgumentParser(
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description=__doc__)

base_parser.add_argument('-v', '--verbose',
                         action='store_true',
                         help='increase output verbosity')


def add_s3_arguments(arg_parser):
    """
    Adds common S3 argument to a parser
    """
    arg_parser.add_argument('--aws-access-key-id',
                            help="public AWS access key.")

    arg_parser.add_argument('--aws-secret-access-key',
                            help="S3 secret access key.")

    arg_parser.add_argument('--s3-bucket-region',
                            default='us-east-1',
                            help="S3 bucket region (default us-east-1)")

    arg_parser.add_argument('--s3-ssenc',
                            action='store_true',
                            help="Enable AWS S3 server-side encryption")

    arg_parser.add_argument('--s3-bucket-name',
                            required=True,
                            help="S3 bucket name for backups.")

    arg_parser.add_argument('--s3-base-path',
                            required=True,
                            help="S3 base path for backups.")

    return arg_parser


def get_s3_connection_host(s3_bucket_region):
    return S3_CONNECTION_HOSTS[s3_bucket_region]


def map_wrap(f):
    """
    Fix annoying multiprocessing.imap bug when sending
    *args and **kwargs
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        return apply(f, *args, **kwargs)
    return wrapper


def check_lzop():
    try:
        subprocess.call([LZOP_BIN, '--version'])
    except OSError:
        sys.exit("{!s} not found on path".format(LZOP_BIN))


def check_pv():
    try:
        subprocess.call([PV_BIN, '--version'])
    except OSError:
        sys.exit("{!s} not found on path".format(PV_BIN))


def compressed_pipe(path, size, rate_limit):
    """
    Returns a generator that yields compressed chunks of
    the given file_path

    compression is done with lzop

    """
    lzop = subprocess.Popen(
        (LZOP_BIN, '--stdout', path),
        bufsize=size,
        stdout=subprocess.PIPE
    )

    if rate_limit > 0:
        pv = subprocess.Popen(
            (PV_BIN, '--rate-limit', str(rate_limit) + 'k'),
            stdin=lzop.stdout,
            stdout=subprocess.PIPE
        )

    while True:
        if rate_limit > 0:
            chunk = pv.stdout.read(size)
        else:
            chunk = lzop.stdout.read(size)
        if not chunk:
            break
        yield StringIO(chunk)


def decompression_pipe(path):
    lzop = subprocess.Popen(
        (LZOP_BIN, '-d', '-o', path),
        stdin=subprocess.PIPE
    )
    return lzop
