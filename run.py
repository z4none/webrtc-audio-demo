#coding:utf-8

import os, sys
pwd = os.path.dirname(__file__)
libs_dir = os.path.join(pwd, "libs")
sys.path.insert(0, libs_dir)

import re
import time
import json
import logging
import tornado.httpserver
import tornado.escape
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.websocket
import traceback
import base64

'''
服务器、客户端通信接口：
通信采用 websocket 方式，可以由客户端主动发送到服务端，也可由服务端主动发送到客户端
因为要传输音频数据，传输内容为二进制
传输内容分为两部分，头 4 字节为帧头，剩下的部分为帧数据
其中帧头的第一字节标明该帧的类型，可以为如下几种：

    0. 文本消息，详细消息数据存放在帧数据中，文本 json 格式
    1. 对讲数据，音频数据存放在帧数据中，二进制

文本消息类型(type)如下：

    audio_open      开始对讲
    audio_close     结束对讲
'''

from tornado.options import define, options
define("port", default=8888, help="run on the given port", type=int)

logging.basicConfig(format='%(asctime)s %(levelname)7s - %(message)s', level=logging.DEBUG)

def json_error(t, d):
    return json.dumps({
        "success"   : False,
        "type"      : t,
        "data"      : d
    }, ensure_ascii=False)

def json_ok(t, d):
    return json.dumps({
        "success"   : True,
        "type"      : t,
        "data"      : d
    }, ensure_ascii=False)

class Application(tornado.web.Application):
    """
    toanado application
    """
    def __init__(self):
        handlers = [
            (r"/"           , MainHandler),
            (r"/ws"         , DataHandler), 
            (r"/login"      , LoginHandler),
        ]
        settings = dict(
            debug = True,
            cookie_secret = "ASDFGHJKL1234567890",
            template_path = os.path.join(pwd, "templates"),
            static_path = os.path.join(pwd, "static"),
            gzip = True
        )
        tornado.web.Application.__init__(self, handlers, **settings)

class MainHandler(tornado.web.RequestHandler):
    def get(self):
        """
        http get handler
        """
        user = self.get_argument("user", "admin")
        user = re.sub(r'</?\w+[^>]*>', '', user)
        
        self.render("index.html", 
            user = user
        )

class LoginHandler(tornado.web.RequestHandler):
    def get(self):
        """
        http get handler
        """        
        self.render("login.html")

jmsg_methods = {}

def jmsg(t):
    def wrapper(func):
        def func_wrapper(*a, **k):
            return func(*a, **k)
        global jmsg_methods
        jmsg_methods[t] = func_wrapper
        return func_wrapper
    return wrapper

class DataHandler(tornado.websocket.WebSocketHandler):
    """
    websocket handler
    """
    clients = set()

    def get_valid_user_id(self):
        user_id_list = [client.user_id for client in DataHandler.clients]
        for i in range(256):
            if not i in user_id_list:
                return i
        return None
    
    def open(self):
        """
        open events
        """
        self.user = self.get_argument("user", "")
        self.user_id = self.get_valid_user_id()
        self.output_bit_rate = int(self.get_argument("output_bit_rate", "16000"))

        logging.info("open %s, %s, %s" % (self.request.remote_ip, self.user, self.output_bit_rate))
        DataHandler.clients.add(self)
        
        self.audio_opend = False
        
        self.write_message("\x00\x00\x00\x00" + json_ok("connect", {"id": self.user_id, "name": self.user}), binary = True)
        for c in DataHandler.clients:
            c.write_message("\x00\x00\x00\x00" + json_ok("user_list", [{"id": c.user_id, "name": c.user} for c in DataHandler.clients]), binary = True)

    def write_response(self, h1, h2 = 0, h3 = 0, h4 = 0, data = ""):
        self.write_message("".join([chr(h1), chr(h2), chr(h3), chr(h4), data]), binary = True)
        
    def on_close(self):
        """
        close event
        """
        logging.info("close, %s" % self.request.remote_ip)
        DataHandler.clients.remove(self)
        for c in DataHandler.clients:
            c.write_message("\x00\x00\x00\x00" + json_ok("user_list", [{"id": c.user_id, "name": c.user} for c in DataHandler.clients]), binary = True)
        
    def on_message(self, message):
        """
        data reviced
        """
        if len(message) < 4:
            # invalid data
            self.close()
            return

        header, data = message[0:4], message[4:]
        if header[0] == chr(0):
            self.on_json_message(header, data)
        elif header[0] == chr(1):
            self.on_audio_data(header, data)

    def on_json_message(self, header, data):
        """
        json message
        """
        global jmsg_methods
        data = json.loads(data)

        t = data.get("type")
        f = jmsg_methods.get(t)
        if f:
            f(self, data)
        else:
            logging.info(u"invalid message: %s" % data)

    @jmsg("audio_open")
    def on_audio_open(self, data):
        logging.info("audio open: %s" % self.user)
        self.audio_opend = True
        self.audio_begin = time.time()
        self.sendto_others("\x00\x00\x00\x00" + json_ok("audio_open", {
            "id" : self.user_id
        }))

    @jmsg("audio_close")
    def on_audio_close(self, data):
        logging.info("audio close: %s" % self.user)
        self.audio_opend = False
        self.audio_end= time.time()
        self.sendto_others("\x00\x00\x00\x00" + json_ok("audio_close", {
            "id"    : self.user_id,
            "begin" : self.audio_begin,
            "end"   : self.audio_end
        }))

    def on_audio_data(self, header, data):
        if not data or not self.audio_opend: 
            return
            
        self.sendto_others("\x01\x00\x00" + chr(self.user_id) + data)
        return

    def sendto_others(self, message):
        for other in DataHandler.clients:
            if other.user_id == self.user_id:
                continue
            other.write_message(message, binary = True)

def main():
    tornado.options.parse_command_line()
    application = Application()
    # application.listen(options.port)
    http_server = tornado.httpserver.HTTPServer(application, ssl_options={
        "certfile": os.path.join(pwd, "ca", "ca.crt"),
        "keyfile" : os.path.join(pwd, "ca", "ca.key"),
    })
    http_server.listen(options.port)
    logging.info("=" * 40)
    logging.info("listening on %s" % options.port)
    try:
        tornado.ioloop.IOLoop.instance().start()
    except:
        pass

if __name__ == "__main__":
    main()
