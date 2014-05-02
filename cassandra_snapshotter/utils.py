import argparse
import functools

base_parser = argparse.ArgumentParser(
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description=__doc__)

base_parser.add_argument('-v', '--verbose',
                    action='store_true',
                    help='increase output verbosity')


def add_s3_arguments(arg_parser):
    '''
    adds common S3 argument to a parser
    '''
    arg_parser.add_argument('--aws-access-key-id',
                        required=True,
                        help='public AWS access key.')

    arg_parser.add_argument('--aws-secret-access-key',
                        required=True,
                        help='S3 secret access key.')

    arg_parser.add_argument('--s3-bucket-name',
                        required=True,
                        help='S3 bucket name for backups.')

    arg_parser.add_argument('--s3-base-path',
                        required=True,
                        help='S3 base path for backups.')

    return arg_parser


def map_wrap(f):
    '''
    fix annoying multiprocessing.imap bug when sending
    *args and **kwargs
    '''
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        return apply(f, *args, **kwargs)
    return wrapper
