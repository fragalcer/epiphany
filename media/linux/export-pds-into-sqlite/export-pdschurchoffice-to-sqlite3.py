#!/usr/bin/env python3.6

import subprocess
import argparse
import logging
import logging.handlers
import shutil
import time
import glob
import os
import re

# Logging.  It's significantly more convenient if this is a global.
log = None

database_temp_name = time.strftime("pdschurchoffice-%Y-%m-%d-%H%M%S.sqlite3")

###############################################################################

def setup_args():
    parser = argparse.ArgumentParser(description='Import PDS data to a new SQLite3 database.')
    parser.add_argument('--sqlite3',
                        default='sqlite3',
                        help='Path to sqlite3 (if not in PATH)')
    parser.add_argument('--pxview',
                        default='pxview',
                        help='pxview binary (it not found in PATH)')

    parser.add_argument('--pdsdata-dir',
                        default='.',
                        help='Path to find PDS data files')
    parser.add_argument('--out-dir',
                        default='.',
                        help='Path to write output sqlite3 database and temporary .sql files')
    parser.add_argument('--temp-dir',
                        default='tmp',
                        help='Path to write temporary files (safe to remove afterwards) relative to the out directory')

    parser.add_argument('--output-database',
                        default="pdschurch.sqlite3",
                        help='Output filename for the final SQLite3 database')
    parser.add_argument('--logfile',
                        default=None,
                        help='Optional output logfile')

    parser.add_argument('--verbose',
                        default=False,
                        action='store_true',
                        help='Enable verbose output')
    parser.add_argument('--debug',
                        default=False,
                        action='store_true',
                        help='Enable extra debugging')

    args = parser.parse_args()

    return args

#------------------------------------------------------------------------------

# Cleanse / sanity check CLI args

def check_args(args):
    pxview_bin = shutil.which(args.pxview)
    if not pxview_bin:
        raise Exception('Cannot find pxview executable')
    args.sqlite3 = shutil.which(args.sqlite3)
    if not args.sqlite3:
        raise Exception('Cannot find sqlite3 executable')
    if not os.path.exists(args.pdsdata_dir):
        raise Exception('Cannot find PDS data dir {}'.format(args.pdsdata_dir))

###############################################################################

def setup_logging(args):
    level=logging.ERROR

    if args.debug:
        level="DEBUG"
    elif args.verbose:
        level="INFO"

    global log
    log = logging.getLogger('pds')
    log.setLevel(level)

    # Make sure to include the timestamp in each message
    f = logging.Formatter('%(asctime)s %(levelname)-8s: %(message)s')

    # Default log output to stdout
    s = logging.StreamHandler()
    s.setFormatter(f)
    log.addHandler(s)

    # Optionally save to a rotating logfile
    if args.logfile:
        s = logging.handlers.RotatingFileHandler(filename=args.logfile,
                                                 maxBytes=(pow(2,20) * 10),
                                                 backupCount=10)
        s.setFormatter(f)
        log.addHandler(s)

###############################################################################

# Remove the temp directory if it's already there

def setup_temps(args):
    name = os.path.join(args.out_dir, args.temp_dir)
    args.temp_dir = name
    shutil.rmtree(args.temp_dir, ignore_errors=True)
    os.makedirs(args.temp_dir, exist_ok=True)

    global database_temp_name
    name = os.path.join(args.out_dir, database_temp_name)
    database_temp_name = name
    if os.path.exists(database_temp_name):
        os.unlink(database_temp_name)

###############################################################################

# Find the PDS database files
def find_pds_files(args):
    dbs = glob.glob('{dir}/*.DB'.format(dir=args.pdsdata_dir))

    return dbs

###############################################################################

# Run sqlite3; we'll be interactively feeding it commands (see below
# for an explanation why).
def open_sqlite3(args):
    sql3_args = list()
    # JMS Why is -echo necessary?  If we don't have it, we seem to get no
    # output :-(
    sql3_args.append('-echo')

    # Write to a temporary database.  We'll rename it at the end.
    global database_temp_name
    sql3_args.append(database_temp_name)

    log.debug("sqlite bin: {}".format(args.sqlite3))
    sqlite3 = subprocess.Popen(args=sql3_args,
                               executable=args.sqlite3,
                               universal_newlines=True,
                               stdin=subprocess.PIPE)
    log.info("Opened sqlite3");

    # This helps SQLite performance considerably (it's slightly risky, in
    # general, because it removes some atomic-ness of transactions, but
    # for this application, it's fine).
    # JMS Apparently this syntax is wrong...?
    #cmd = 'PRAGMA {db}.synchronous=0;\n'.format(db=database_name)
    #sqlite3.stdin.write('PRAGMA {db}.synchronous=0;\n'.format(db=database_name))

    return sqlite3


###############################################################################

def process_db(args, db, sqlite3):
    log.info("=== PDS table: {full}".format(full=db))

    results = re.search('(.+).DB$', os.path.basename(db))
    table_base = results.group(1)

    # PDS has "PDS" and "PDS[digit]" tables.  "PDS" is the real one;
    # skip "PDS[digit]" tables.  Sigh.  Ditto for RE, SCH.
    if (re.search('^PDS\d+$', table_base, flags=re.IGNORECASE) or
        re.search('^RE\d+$', table_base, flags=re.IGNORECASE) or
        re.search('^RE\d+.DB$', table_base, flags=re.IGNORECASE) or
        re.search('^SCH\d+$', table_base, flags=re.IGNORECASE)):
        log.info("   ==> Skipping bogus {short} table".format(short=table_base))
        return

    # PDS also has a duplicate table "resttemp_db" in the AskRecNum
    # and RecNum databases.  They appear to be empty, so just skip
    # them.
    if (re.search('^AskRecNum$', table_base, flags=re.IGNORECASE) or
        re.search('^RecNum$', table_base, flags=re.IGNORECASE)):
        log.info("   ==> Skipping bogus {short} table".format(short=table_base))
        return

    # We dont' currently care about the *GIANT* databases (that take
    # -- literally -- hours to import on an RPi).
    if (re.search('fund', table_base, flags=re.IGNORECASE)):
        log.info("   ==> Skipping giant {short} table".format(short=table_base))
        return

    # We have the PDS SMB file share opened as read-only, and pxview
    # doesn't like opening files in read-only mode.  So we have to
    # copy the files to a read-write location first.

    # Yes, we use "--sql" here, not "--sqlite".  See the comment below
    # for the reason why.  :-(
    pxview_args = list()
    pxview_args.append(args.pxview)
    pxview_args.append('--sql')

    shutil.copy(db, args.temp_dir)
    temp_db = os.path.join(args.temp_dir, '{file}.DB'.format(file=table_base))
    pxview_args.append(temp_db)

    # Is there an associated blobfile?
    blobname = '{short}.MB'.format(short=table_base)
    blobfile = "{dir}/{name}".format(dir=args.pdsdata_dir,
                                     name=blobname)
    if os.path.exists(blobfile):
        shutil.copy(blobfile, args.temp_dir)
        temp_blobfile = os.path.join(args.temp_dir, blobname)
        pxview_args.append('--blobfile={file}'.format(file=temp_blobfile))

    # Sadly, we can't have pxview write directly to the sqlite
    # database because PDS has some field names that are SQL reserved
    # words.  :-( Hence, we have to have pxview output the SQL, read
    # the SQL here in Python, then twonk the SQL a bit, and then we
    # can import it into the sqlite3 database using the sqlite3
    # executable.
    sql_file = '{dir}/{base}.sql'.format(dir=args.out_dir, base=table_base)
    if os.path.exists(sql_file):
        os.unlink(sql_file)
    pxview_args.append('-o')
    pxview_args.append(sql_file)

    # Write out the SQL file
    if args.debug:
        log.debug('=== PXVIEW command: {pxview} {args}'
                  .format(pxview=args.pxview, args=pxview_args))
    subprocess.run(args=pxview_args)

    if args.debug:
        log.debug('Final SQL:')

    # Must use latin-1 encoding: utf-8 will choke on some of the
    # characters (not sure exactly which ones -- e.g., there are
    # characters in Fam.sql that will cause exceptions in utf-8
    # decoding).
    sf = open(sql_file, 'r', encoding='latin-1')

    # Go through all the lines in the file
    f = re.IGNORECASE
    transaction_started = False
    for line in list(sf):

        # PDS uses some fields named "order", "key", "default", etc.,
        # which are keywords in SQL
        line = re.sub(r'\border\b', 'pdsorder', line, flags=f)
        line = re.sub(r'\bkey\b', 'pdskey', line, flags=f)
        line = re.sub(r'\bdefault\b', 'pdsdefault', line, flags=f)
        line = re.sub(r'\bcheck\b', 'pdscheck', line, flags=f)
        line = re.sub(r'\bboth\b', 'pdsboth', line, flags=f)
        line = re.sub(r'\bowner\b', 'pdsowner', line, flags=f)
        line = re.sub(r'\baccess\b', 'pdsaccess', line, flags=f)
        line = re.sub(r'\bsql\b', 'pdssql', line, flags=f)

        # SQLite does not have a boolean class; so turn TRUE and FALSE
        # into 1 and 0.
        line = re.sub('TRUE', '1', line)
        line = re.sub('FALSE', '0', line)

        # PDS Puts dates into YYYY-MM-DD, which sqlite3 will turn into
        # a mathematical expression.  So quote it so that sqlite3 will
        # treat it as a string.
        line = re.sub(r', (\d\d\d\d-\d\d-\d\d)([,)])', r', "\1"\2', line)
        # Must do this twice (!) because Python re will not replace
        # two overlapping patterns (i.e., if the string contains ',
        # 2005-03-03, 2005-04-04', those two patterns overlap, and the
        # 2nd one will not be replaced).
        line = re.sub(r', (\d\d\d\d-\d\d-\d\d)([,)])', r', "\1"\2', line)

        if args.debug:
            log.debug("SQL: {}".format(line.rstrip()))

        # If we're insertting and we haven't started the transaction,
        # start the transaction.
        if not transaction_started and re.search('insert', line, flags=re.IGNORECASE):
            sqlite3.stdin.write('BEGIN TRANSACTION;\n')
            transaction_started = True

        sqlite3.stdin.write(line)

    if transaction_started:
        sqlite3.stdin.write('END TRANSACTION;\n')

    sf.close()
    os.unlink(sql_file)

###############################################################################

# Close down sqlite3
def close_sqlite3(sqlite3):
    sqlite3.stdin.write('.exit\n')
    sqlite3.communicate()

# Rename the temp database to the final database name
def rename_sqlite3_database(args):
    # Once we are done writing the new database, atomicly rename it into
    # the final database name.
    global database_temp_name
    final_filename = os.path.join(args.out_dir, args.output_database)
    os.rename(src=database_temp_name, dst=final_filename)

###############################################################################

def main():
    args = setup_args()
    check_args(args)
    setup_logging(args)

    setup_temps(args)
    dbs = find_pds_files(args)
    sqlite3 = open_sqlite3(args)
    for db in dbs:
        process_db(args, db, sqlite3)
    close_sqlite3(sqlite3)
    rename_sqlite3_database(args)

if __name__ == '__main__':
    main()
