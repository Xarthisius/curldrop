import subprocess
import logging
import datetime
import os
import json
from werkzeug import secure_filename
from uuid import uuid4
import sqlite3
import tornado.ioloop
import tornado.web
from tornado.httpserver import HTTPServer
from contextlib import closing
from mediagoblin.media_types.image import ACCEPTED_EXTENSIONS

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)-6s: %(levelname)s - %(message)s')

config = {
    'DATABASE': os.environ.get("DATABASE", 'files.db'),
    'UPLOADDIR': os.environ.get("UPLOADDIR", 'uploads/'),
    'BASEURL': os.environ.get("BASEURL", 'http://example.com/'),
    'BUFFSIZE': int(os.environ.get("BUFFSIZE", 50L * 1024 ** 2)),
    'EXPIRES': int(os.environ.get("EXPIRES", 3600 * 24)),
    'PORT': os.environ.get("PORT", 8888),
    'SERVERBUFF': int(os.environ.get("SERVERBUFF", 15L * 1024 ** 3)),
}


def get_now():
    # return int(datetime.datetime.now().timestamp())
    dt = datetime.datetime.now()
    return (dt - datetime.datetime(1970, 1, 1)).total_seconds()


def get_filename(file_id):
    with closing(sqlite3.connect(config['DATABASE'])) as db:
        cur = db.execute(
            'SELECT originalname FROM files WHERE file_id = ?', [file_id])
        try:
            filename = [row for row in cur.fetchall()][0][0]
        except IndexError:
            filename = False
    return filename


@tornado.web.stream_body
class StreamHandler(tornado.web.RequestHandler):

    def _set_custom_head(self, filename, ffname):
        self.set_header('Content-Type', 'application/octet-stream')
        self.set_header('Content-Disposition', 'attachment; filename=' +
                        filename)
        self.set_header('Content-Length', str(os.path.getsize(ffname)))

    def get(self, file_id):
        filename = get_filename(file_id)
        if filename:
            t_ffname = os.path.join(config['UPLOADDIR'], file_id)
            file_not_found = True
            for ext in ACCEPTED_EXTENSIONS:
                ffname = t_ffname + '.' + ext
                if os.path.isfile(ffname):
                    file_not_found = False
                    break
            if file_not_found:
                raise tornado.web.HTTPError(404, 'Invalid archive')
            self._set_custom_head(filename, ffname)
            with open(ffname, 'r') as f:
                while True:
                    data = f.read(config["BUFFSIZE"])
                    if not data:
                        break
                    self.write(data)
                    self.flush()
            self.finish()
        else:
            raise tornado.web.HTTPError(404, 'Invalid archive')

    def head(self, file_id):
        filename = get_filename(file_id)
        if filename:
            ffname = os.path.join(config['UPLOADDIR'], file_id)
            self._set_custom_head(filename, ffname)
            self.finish()
        else:
            raise tornado.web.HTTPError(404, 'Invalid archive')

    def put(self, userfile):
        filename, ext = os.path.splitext(userfile)
        if ext.strip('.') not in ACCEPTED_EXTENSIONS:
            raise tornado.web.HTTPError(400, 'File has wrong extension')
        self.read_bytes = 0L
        self.file_id = str(uuid4())[:8]
        self.delete_id = str(uuid4())[:8]
        self.ffname = os.path.join(config['UPLOADDIR'], self.file_id) + ext
        self.tempfile = open(self.ffname, "wb")
        self.request.request_continue()
        self.read_chunks()
        self.uf = userfile

    def read_chunks(self, chunk=''):
        self.read_bytes += long(len(chunk))
        if chunk:
            logging.info('Received {} bytes'.format(len(chunk)))
            self.tempfile.write(chunk)
            # self.md5.update(chunk)
        chunk_length = min(1024 * 1024 * 50L,
                           self.request.content_length - self.read_bytes)
        if chunk_length > 0L:
            self.request.connection.stream.read_bytes(
                chunk_length, self.read_chunks)
        else:
            self.tempfile.close()
            self.uploaded()

    def uploaded(self):
        with closing(sqlite3.connect(config['DATABASE'])) as db:
            db.execute(
                'INSERT INTO files (file_id, delete_id, timestamp, ip, originalname) VALUES (?, ?, ?, ?, ?)',
                [self.file_id, self.delete_id, str(get_now()),
                 self.request.remote_ip, secure_filename(self.uf)])
            db.commit()
        subprocess.call("python commit.py " + os.path.basename(self.ffname),
                        shell=True)
        self.write('Open in your browser: https://images.hub.yt/u/fido/m/' +
                   os.path.basename(self.ffname).replace('.', '-') + '/\n')
        self.write('Download: curl -JO ' + config['BASEURL'] + "upload/" +
                   self.file_id + '\n')
        self.write('Delete: curl ' + config['BASEURL'] + "upload/delete/" +
                   self.delete_id + '\n')
        self.finish()


class FileListHandler(tornado.web.RequestHandler):

    def get(self):
        result = []
        with closing(sqlite3.connect(config['DATABASE'])) as db:
            cur = db.execute('SELECT file_id, originalname FROM files')
            for fid, fname in cur.fetchall():
                if fname:
                    result.append({"url": "%s%s" % (config["BASEURL"], fid),
                                   "name": fname})
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(result))
        self.finish()


def remove_expired():
    return
    now = get_now()
    with closing(sqlite3.connect(config['DATABASE'])) as db:
        cur = db.execute('SELECT file_id, timestamp FROM files')
        for row in cur.fetchall():
            if (now - row[1]) > config['EXPIRES']:
                os.remove(os.path.join(config['UPLOADDIR'], row[0]))
                db.execute('DELETE FROM files WHERE file_id = ?	', [row[0]])
                db.commit()


if __name__ == "__main__":
    application = tornado.web.Application([
        (r"/list_files", FileListHandler),
        (r"/(.*)", StreamHandler),
    ])
    server = HTTPServer(application, max_buffer_size=15L * 1024 ** 3)
    server.listen(8888)
    tornado.ioloop.IOLoop.instance().start()
