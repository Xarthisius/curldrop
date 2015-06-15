#!/usr/bin/env python
import os
import tornado
from curldrop import StreamHandler, config
from contextlib import closing
import sqlite3

schema = '''drop table if exists files;
create table files (
  id integer primary key autoincrement,
  file_id text not null,
  timestamp integer not null,
  ip text not null,
  originalname text not null
);'''

if not os.path.isfile(config['DATABASE']):
    with closing(sqlite3.connect(config['DATABASE'])) as db:
        db.cursor().executescript(schema)
        db.commit()

if not os.path.isdir(config['UPLOADDIR']):
    os.makedirs(config['UPLOADDIR'])

application = tornado.web.Application([
    (r"/list_files", FileListHandler),
    (r"/(.*)", StreamHandler),
])
server = tornado.httpserver.HTTPServer(application,
                                       max_buffer_size=config["SERVERBUFF"])
server.listen(config["PORT"])
tornado.ioloop.IOLoop.instance().start()
