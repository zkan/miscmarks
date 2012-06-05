import webapp2
import template
import re
import hashlib
import hmac
import json
import time
import logging
from google.appengine.ext import db
from google.appengine.api import memcache

# Global functions and variables
USER_RE = re.compile(r"^[a-zA-Z0-9_-]{3,20}$")
def valid_username(username):
    return username and USER_RE.match(username)

PASS_RE = re.compile(r"^.{3,20}$")
def valid_password(password):
    return password and PASS_RE.match(password)

EMAIL_RE  = re.compile(r'^[\S]+@[\S]+\.[\S]+$')
def valid_email(email):
    return not email or EMAIL_RE.match(email)

COOKIE_RE = re.compile(r'.+=; Path=/')
def valid_cookie(cookie):
    return cookie and COOKIE_RE.match(cookie)

def blog_key(name = 'default'):
    return db.Key.from_path('blogs', name)

# Data models
class User(db.Model):
    username = db.StringProperty(required = True)
    password = db.TextProperty(required = True)
    email = db.StringProperty(required = False)
    created = db.DateTimeProperty(auto_now_add = True)
    last_modified = db.DateTimeProperty(auto_now = True)

class Post(db.Model):
    subject = db.StringProperty(required = True)
    content = db.TextProperty(required = True)
    created = db.DateTimeProperty(auto_now_add = True)
    last_modified = db.DateTimeProperty(auto_now = True)

    def render(self):
        self._render_text = self.content.replace('\n', '<br>')
        return template.render_str("post.html", p = self)

# Classes
class BlogFront(template.TemplateHandler):
    def get(self):
        age = memcache.get('age')
        if age is None:
            logging.error('AGE INITIALIZED')
            age = 0
            memcache.set('age', time.time())
        else:
            age = int(time.time() - age)
            
        logged_in = False
        username = ''
        user_id = self.request.cookies.get('user_id')
        if user_id:
            logged_in = True
            key = db.Key.from_path('User', int(user_id), parent=blog_key())
            u = db.get(key)
            username = u.username
            
#        posts = db.GqlQuery("select * from Post order by created desc limit 10")      
        posts = Post.all().order('-created')
        self.render('front.html', logged_in = logged_in, 
                                  username = username, 
                                  posts = posts, 
                                  age = age)

class PostPage(template.TemplateHandler):
    def get(self, post_id):
        age = memcache.get('age%s' % post_id)
        if age is None:
            logging.error('AGE INITIALIZED')
            age = 0
            memcache.set('age%s' % post_id, time.time())
        else:
            age = int(time.time() - age)

        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)
        
        logged_in = False
        username = ''
        user_id = self.request.cookies.get('user_id')
        if user_id:
            logged_in = True
            key = db.Key.from_path('User', int(user_id), parent=blog_key())
            u = db.get(key)
            username = u.username

        if not post:
            self.error(404)
            return

        self.render("permalink.html", logged_in = logged_in, 
                                      username = username, 
                                      post = post, 
                                      age = age)

class NewPost(template.TemplateHandler):
    def get(self):
        user_id = self.request.cookies.get('user_id')
        if not user_id:
           self.redirect('/blog/login')

        self.render("newpost.html")

    def post(self):
        subject = self.request.get('subject')
        content = self.request.get('content')

        if subject and content:
            p = Post(parent = blog_key(), 
                     subject = subject, 
                     content = content)
            p.put()

#            self.write(p.key().id())
#            t = Post.get_by_id(p.key().id())
#            self.write(t.subject)

            self.redirect('/blog/%s' % str(p.key().id()))
        else:
            error = 'subject and content, please!'
            self.render("newpost.html", subject = subject, 
                                        content = content, 
                                        error = error)

class Welcome(template.TemplateHandler):
    def get(self):
        user_id = self.request.cookies.get('user_id')
        if user_id:
            key = db.Key.from_path('User', int(user_id), parent=blog_key())
            u = db.get(key)
            username = u.username

            if valid_username(username):
                self.render('welcome.html', username = username)
            else: 
                self.redirect('/blog/signup')
        else: 
            self.redirect('/blog/signup')

class SignUp(template.TemplateHandler):
    def get(self):
        self.render('signup-form.html')

    def post(self):
        have_error = False
        username = self.request.get('username')
        password = self.request.get('password')
        verify = self.request.get('verify')
        email = self.request.get('email')
        
        params = dict(username = username, 
                      email = email)

        if not valid_username(username):
            params['error_username'] = "That's not a valid username."
            have_error = True

        if not valid_password(password):
            params['error_password'] = "That wasn't a valid password."
            have_error = True
        elif password != verify:
            params['error_verify'] = "Your passwords didn't match."
            have_error = True

        if not valid_email(email):
            params['error_email'] = "That's not a valid email."
            have_error = True
        
        if have_error:
            self.render('signup-form.html', **params)
        else:
            query = db.GqlQuery("select * from User where username = :username", username = username)
            user_in_db = query.fetch(1)
            
            if not user_in_db:
                u = User(parent = blog_key(),
                         username = username, 
                         password = password, 
                         email = email)
                u.put()

                user_id = str(u.key().id())
                cookie_str = str('user_id=%s; Path=/' % user_id)
                self.response.headers['Content-Type'] = 'text/plain'
                self.response.headers.add_header('Set-Cookie', cookie_str)
                self.redirect('/blog/welcome')
            else:
               params['error_username'] = "That user already exists."
               self.render('signup-form.html', **params)

class LogIn(template.TemplateHandler):
    def get(self):
        self.render('login-form.html')
    
    def post(self):
        have_error = False
        username = str(self.request.get('username'))
        password = str(self.request.get('password'))
        
        query = db.GqlQuery("select * from User where username = :username", username = username)
        user_in_db = query.get()
        if user_in_db:
            if user_in_db.password == password:
                user_id = user_in_db.key().id()
                cookie_str = str('user_id=%s; Path=/' % user_id)
                self.response.headers['Content-Type'] = 'text/plain'
                self.response.headers.add_header('Set-Cookie', cookie_str)
                self.redirect('/blog/welcome')
            else:
                have_error = True
        else:
            have_error = True
        
        if have_error:
            error = 'Invalid login'
            self.render('login-form.html', username = username, error = error)

class LogOut(template.TemplateHandler):
    def get(self):
        self.response.headers['Content-Type'] = 'text/plain'
        cookie_str = 'user_id=; Path=/'
        if valid_cookie(cookie_str):
            self.response.headers.add_header("Set-Cookie", cookie_str)
            self.redirect('/blog/signup')

def generate_json(posts):
    jc = ''
#    xxx.strftime("%b %d, %Y")
    if len(posts) > 1:
        jc = ', '.join("{\"content\": \"%s\", \"created\": \"%s\", \"last_modified\": \"%s\", \"subject\": \"%s\"}" % (p.content.replace('"', '\\\\"').replace("'", '\\\''), p.created.strftime("%a %b %d %H:%M:%S %Y"), p.last_modified.strftime("%a %b %d %H:%M:%S %Y"), p.subject.replace('"', '\\\\"').replace("'", '\\\'')) for p in posts)
        
        jc = '[' + jc + ']'
    else:
        p = posts[0]
        jc = "{\"content\": \"%s\", \"created\": \"%s\", \"last_modified\": \"%s\", \"subject\": \"%s\"}" % (p.content.replace('"', '\\\\"').replace("'", '\\\''), p.created.strftime("%a %b %d %H:%M:%S %Y"), p.last_modified.strftime("%a %b %d %H:%M:%S %Y"), p.subject.replace('"', '\\\\"').replace("'", '\\\''))

    return jc

class JSONPage(template.TemplateHandler):
    def get(self, post_id):
        self.response.headers['Content-Type'] = 'application/json; charset=UTF-8'
        if post_id:
            key = db.Key.from_path('Post', int(post_id), parent=blog_key())
            post = db.get(key)

            if not post:
                self.error(404)
                return

            posts = [post]
            self.write(generate_json(posts))
        else:
            posts = Post.all().order('-created')
            posts = list(posts)
            self.write(generate_json(posts))

class FlushCache(template.TemplateHandler):
    def get(self):
        memcache.flush_all()
        self.redirect('/blog')

# Handlers
app = webapp2.WSGIApplication([('/blog/?', BlogFront),
                               ('/blog/(\d+)', PostPage),
                               ('/blog/newpost', NewPost), 
                               ('/blog/welcome', Welcome), 
                               ('/blog/signup', SignUp), 
                               ('/blog/login', LogIn),
                               ('/blog/logout', LogOut), 
                               ('/blog/flush', FlushCache), 
                               ('/blog/(\d+)?\.json', JSONPage), 
                               ], 
                              debug = True)

