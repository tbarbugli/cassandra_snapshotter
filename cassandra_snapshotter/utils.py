import argparse
import functools

S3_CONNECTION_HOSTS = {
    'us-east-1': 's3.amazonaws.com',
    'us-west-2': 's3-us-west-2.amazonaws.com',
    'us-west-1': 's3-us-west-1.amazonaws.com',
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
                        required=True,
                        help="public AWS access key.")

    arg_parser.add_argument('--s3-bucket-region',
                    default='us-east-1',
                    help="S3 bucket region (default us-east-1)")

    arg_parser.add_argument('--s3-ssenc',
                            action='store_true',
                            help="Enable AWS S3 server-side encryption")

    arg_parser.add_argument('--aws-secret-access-key',
                        required=True,
                        help="S3 secret access key.")

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
