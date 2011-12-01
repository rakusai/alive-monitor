# -*- coding: utf-8 -*-

import sys
import os

from google.appengine.dist import use_library
use_library('django', '1.2')

import re
import urllib
import datetime
import base64

import logging

from google.appengine.ext.webapp import template
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.ext import db
from google.appengine.api import memcache
from google.appengine.api import urlfetch
from google.appengine.api.labs import taskqueue
from google.appengine.api import mail

class Entry(db.Model):
    title = db.StringProperty()
    url = db.StringProperty()
    alive = db.BooleanProperty(default=True)
    started = db.BooleanProperty(default=False)
    error_reason = db.StringProperty()
    keyword = db.StringProperty()
    date = db.DateTimeProperty(auto_now_add=True)
    update = db.DateTimeProperty(auto_now=True)

class MainPage(webapp.RequestHandler):
    def get(self):
        entries = Entry.all().order("title").fetch(100)

        lastchecked = memcache.get("lastcheckedtime")
        diffsec = 0
        if lastchecked:
            diff = datetime.datetime.now() - lastchecked
            diffsec =  diff.seconds
            if diffsec == 0:
                diffsec = 1
    
        template_values = {
            "entries" : entries,
            "diffsec" : diffsec,
        }
        path = os.path.join(os.path.dirname(__file__), 'views/home.html')
        self.response.out.write(template.render(path, template_values))

            
class EditPage(webapp.RequestHandler):

    def need_admin(self):
        user = users.get_current_user()
        if not user:
            self.redirect(users.create_login_url(self.request.uri))
            return False       
        if not users.is_current_user_admin():     
            self.response.out.write("Sorry, but only admin can edit. <a href=\"%s\">Log out</a>" % users.create_logout_url("/"))
            return False
            
        return True

    def get(self):
        if not self.need_admin():
            return

        id = self.request.get('id')
        if id:
            entry = Entry.get_by_id(int(id))
        else:
            entry = None
            
        template_values = {
            "id" : id,
            "entry" : entry
        }
        path = os.path.join(os.path.dirname(__file__), 'views/edit.html')
        self.response.out.write(template.render(path, template_values))

    
    def post(self):
        if not self.need_admin():
            return

        id = self.request.get('id')
        url = self.request.get('url')
        title = self.request.get('title')
        keyword = self.request.get('keyword')
        delete = int(self.request.get('delete',0))
        
        if not url or not title:
            self.response.out.write("please input url and title")
            return            
        
        if not id:
            entry = Entry()
        else:
            entry = Entry.get_by_id(int(id))
            if not entry:
                self.response.out.write("entry not found")
                return
            if delete:
                entry.delete()
                self.redirect("/")
                return

        entry.title = title
        if entry.url != url or entry.keyword != keyword:
            entry.started = False
        entry.url = url 
        entry.keyword = keyword
        entry.put()
        
        self.redirect("/")
        
def email_notification(entry):
    subject = ''
    body = ''
    if entry.alive:
        subject = entry.title + " is alive"
    else:
        subject = entry.title + " is down (" + entry.error_reason + ")"
    body = subject + "\n\n" + "http://alive-monitor.appspot.com/"
        
    mail.send_mail(sender="Alive Monitor <rakusai@gmail.com>",
                  to="rakusai@gmail.com",
                  subject=subject,
                  body=body)        
    logging.info("Sent Email:" + subject)


class Check(webapp.RequestHandler):
    def get(self):
        entries = Entry.all().fetch(100)
        
        for entry in entries:
            alive = True
            error_reason = ''
            try:
                result = urlfetch.fetch(entry.url,deadline=10)
                if result.status_code != 200:
                    alive = False
                    error_reason = str(result.status_code) + " Error"
                elif entry.keyword:
                    if not re.search(entry.keyword, result.content):
                        alive = False
                        error_reason = "Missing Keyword Error"
            except urlfetch.DownloadError:
                alive = False               
                error_reason = "Download Error"
            except urlfetch.InvalidURLError:
                alive = False
                error_reason = "Invalid URL Error"
            except:
                alive = False               
                error_reason = "Enexpected Error"
            
            if entry.alive != alive or not entry.started:
                entry.started = True
                entry.error_reason = error_reason
                entry.alive = alive
                email_notification(entry)
                entry.put()
            else:
                if not alive:
                    diff = datetime.datetime.now() - entry.update
                    if diff.seconds > 60*60:
                        email_notification(entry)
                        entry.put()                

        now = datetime.datetime.now()
        memcache.set("lastcheckedtime",now)

        self.response.out.write("Done")

application = webapp.WSGIApplication(
                                     [('/', MainPage),
                                     ('/edit', EditPage),
                                     ('/check', Check)],
                                     debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()