#!/usr/bin/env python2.7

# settings are read from the files mirror_url and mirror_path. These
# files should just contain url and path, respectively, without
# anything else.
# #### IMPORTANT NOTE ####
# In mirror_url and mirror_path, please provide URL and path without
# trailing slashes!

import hashlib, requests, os, sys, time

url_base = open("mirror_url").read().strip()
mirror_root = open("mirror_path").read().strip()
max_retries = 5                                         # times to retry to download the file
sleep_between_retries = 15.0				# time between retries in seconds
sleep_before_delete = 5.0				# time before deleting files after sync is finished

digest_name = "digest.md5"
digest_new_name = "digest.new.md5"

print
print "Mirror URL:", url_base
print "Mirror local path:", mirror_root
print

######################################################################
# helper functions

# calculate md5 hash of a file given by its name
def md5(fname):
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

# retrieve a file and return true if it satisfies given md5 hash. to
# skip md5 checking, set md5expected to None. this function would
# create required directories if needed
def get(path_relative, md5expected, path_relative_new = None, retry = 0, force_full = False):
    if path_relative_new is None:
        path_relative_new = path_relative

    path = os.path.join(mirror_root, path_relative_new)
    if os.path.exists(path) and md5(path) == md5expected:
        print "File %s available already, skipping" % path
        return True

    path_download = path + ".download"
    url = url_base + "/" + path_relative

    dn = os.path.dirname(path)
    if not os.path.exists(dn):
        os.makedirs(dn)

    block_size = 1000 * 1000 # 1MB
    first_byte = os.path.getsize(path_download) if not force_full and os.path.exists(path_download) else 0
    file_mode = 'ab' if first_byte else 'wb'
    if retry or first_byte > 0: print 'Starting download at %.1fMB' % (first_byte / 1e6)
    file_size = -1
    try:
        file_size = int(requests.head(url).headers['Content-length'])
        if retry or first_byte > 0: print 'File size is %s' % file_size
        headers = {"Range": "bytes=%s-" % first_byte}
        r = requests.get(url, headers=headers, stream=True)
        with open(path_download, file_mode) as f:
            for chunk in r.iter_content(chunk_size=block_size):
                if chunk: # filter out keep-alive new chunks
                    f.write(chunk)
    except IOError as e:
        print 'IO Error - %s' % e
    finally:
        # rename the temp download file to the correct name if fully downloaded
        if file_size == os.path.getsize(path_download):
            # if there's a hash value, validate the file
            if md5expected is None or md5(path_download) == md5expected:
                os.rename(path_download, path)
                return True
            else:
                print "MD5 mismatch:", url, md5(path_download), md5expected
                if first_byte > 0:
                    print "Retry full download"
                    return get(path_relative, md5expected, path_relative_new, retry, True)

        if retry < max_retries:
            time.sleep(sleep_between_retries)
            print "Trying again:", url
            return get(path_relative, md5expected, path_relative_new, retry + 1)

        if file_size == -1:
            print 'Error getting Content-Length from server: %s' % url

    print "Download failed:", url
    return False

# load digest into a list
def load_digest(dname):
    digest = []
    try:
        for l in open(os.path.join(mirror_root, dname), 'r'):
            line = l.split()
            digest.append( { "md5": line[0], "time": line[1], "name": line[2] } )
    except: pass
    return digest

# convert digest into dictionary format to speedup comparisons
def digest2dict(digest):
    do = {}
    for i in digest: do[ i["name"] ] = i
    return do

# find new files
def files_to_get(digest_old, digest_new):
    do = digest2dict(digest_old)
    f = []
    for k in digest_new:
        name = k["name"]
        if name not in do or k != do[name]:
            f.append(name)
    return f


#################################################
# main function

# get md5 of a digest
if not get( digest_name + ".bz2.md5", None, digest_new_name + ".bz2.md5" ):
    sys.exit(-1)

digest_md5_old = load_digest( digest_name + ".bz2.md5" )
digest_md5_new = load_digest( digest_new_name + ".bz2.md5" )

if len( files_to_get(digest_md5_old, digest_md5_new) ) == 0:
    print "Digest has not changed - nothing to sync\n"
    sys.exit(0)

print "Fetching digest"
if not get( digest_name + ".bz2", digest2dict(digest_md5_new)[digest_name + ".bz2"]["md5"],
            digest_new_name + ".bz2" ):
    sys.exit(-1)

# extract digest
os.system("bunzip2 -k -f " + os.path.join(mirror_root, digest_new_name) + ".bz2")

#########################################
# download loop
digest_old = load_digest( digest_name )
digest_new = load_digest( digest_new_name )
updated_files = files_to_get(digest_old, digest_new)

print "\nNeed to get", len(updated_files), "files"
digest_new_dict = digest2dict(digest_new)
counter = 0
for f in updated_files:
    if not get(f, digest_new_dict[f]["md5"]):
        sys.exit(-1)
    counter += 1
    print "Left:", len(updated_files) - counter, " / downloaded:", f

# all is fine and we are up to date. have to move digests to get ready
# for the next run
os.rename( os.path.join(mirror_root, digest_new_name), os.path.join(mirror_root, digest_name) )
os.rename( os.path.join(mirror_root, digest_new_name + ".bz2"), os.path.join(mirror_root, digest_name + ".bz2") )
os.rename( os.path.join(mirror_root, digest_new_name + ".bz2.md5"), os.path.join(mirror_root, digest_name + ".bz2.md5") )

print "\nAll files downloaded"

#########################################
# cleanup

# to ensure that we don't delete digest, its compressed form and its own digest during cleanup
digest_new_dict[digest_name] = {}
digest_new_dict[digest_name + ".bz2"] = {}
digest_new_dict[digest_name + ".bz2.md5"] = {}

toremove = []
for root, dirs, files in os.walk(mirror_root, followlinks=False):
    if root == mirror_root: r = ""
    else: r = root[ len(mirror_root)+1: ] + "/" # to remove trailing slash as well
    for f in files:
        if r + f not in digest_new_dict:
            if len(r) > 0: relname = os.path.join(r, f)
            else: relname = f
            toremove.append( os.path.join( mirror_root, relname) )

if len(toremove) > 0:
    print "\nFiles not needed anymore"
    for f in toremove:
        print f

    print
    print "Sleeping for %d seconds before deleting files" % sleep_before_delete
    print
    time.sleep( sleep_before_delete )

    for f in toremove:
        print "Removing", f
        os.remove(f)


print "\nAll Done\n"
