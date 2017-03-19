#
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2013 IBM Corp.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Utility methods for working with WSGI servers."""

import abc
import errno
import os
import signal
import sys
import time

import eventlet
from eventlet.green import socket
from eventlet.green import ssl
import eventlet.greenio
import eventlet.wsgi
import functools
from oslo_concurrency import processutils
from oslo_config import cfg
import oslo_i18n as i18n
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils import importutils
from paste import deploy
import routes
import routes.middleware
import six
import webob.dec
import webob.exc

from knob.common import exception
from knob.common.i18n import _
from knob.common.i18n import _LE
from knob.common.i18n import _LI
from knob.common.i18n import _LW
from knob.common import serializers


LOG = logging.getLogger(__name__)
URL_LENGTH_LIMIT = 50000

api_opts = [
    cfg.IPOpt('bind_host', default='0.0.0.0',
              help=_('Address to bind the server. Useful when '
                     'selecting a particular network interface.'),
              deprecated_group='DEFAULT'),
    cfg.PortOpt('bind_port', default=2712,
                help=_('The port on which the server will listen.'),
                deprecated_group='DEFAULT'),
    cfg.IntOpt('backlog', default=4096,
               help=_("Number of backlog requests "
                      "to configure the socket with."),
               deprecated_group='DEFAULT'),
    cfg.StrOpt('cert_file',
               help=_("Location of the SSL certificate file "
                      "to use for SSL mode."),
               deprecated_group='DEFAULT'),
    cfg.StrOpt('key_file',
               help=_("Location of the SSL key file to use "
                      "for enabling SSL mode."),
               deprecated_group='DEFAULT'),
    cfg.IntOpt('workers', min=0, default=2,
               help=_("Number of workers for knob service. "
                      "Default value 0 means, that service will start number "
                      "of workers equal number of cores on server."),
               deprecated_group='DEFAULT'),
    cfg.IntOpt('max_header_line', default=16384,
               help=_('Maximum line size of message headers to be accepted. '
                      'max_header_line may need to be increased when using '
                      'large tokens (typically those generated by the '
                      'Keystone v3 API with big service catalogs).')),
    cfg.IntOpt('tcp_keepidle', default=600,
               help=_('The value for the socket option TCP_KEEPIDLE.  This is '
                      'the time in seconds that the connection must be idle '
                      'before TCP starts sending keepalive probes.')),
]
api_group = cfg.OptGroup('knob_api')
cfg.CONF.register_group(api_group)
cfg.CONF.register_opts(api_opts,
                       group=api_group)


wsgi_elt_opts = [
    cfg.BoolOpt('wsgi_keep_alive',
                default=True,
                help=_("If False, closes the client socket connection "
                       "explicitly.")),
    cfg.IntOpt('client_socket_timeout', default=900,
               help=_("Timeout for client connections' socket operations. "
                      "If an incoming connection is idle for this number of "
                      "seconds it will be closed. A value of '0' means "
                      "wait forever.")),
]
wsgi_elt_group = cfg.OptGroup('eventlet_opts')
cfg.CONF.register_group(wsgi_elt_group)
cfg.CONF.register_opts(wsgi_elt_opts,
                       group=wsgi_elt_group)
json_size_opt = cfg.IntOpt('max_json_body_size',
                           default=1048576,
                           help=_('Maximum raw byte size of JSON request body.'
                                  ' Should be larger than max_template_size.'))
cfg.CONF.register_opt(json_size_opt)


def list_opts():
    yield None, [json_size_opt]
    yield 'knob_api', api_opts
    yield 'eventlet_opts', wsgi_elt_opts


def get_bind_addr(conf, default_port=None):
    """Return the host and port to bind to."""
    return (conf.bind_host, conf.bind_port or default_port)


def get_socket(conf, default_port):
    """Bind socket to bind ip:port in conf.

    Note: Mostly comes from Swift with a few small changes...

    :param conf: a cfg.ConfigOpts object
    :param default_port: port to bind to if none is specified in conf

    :returns : a socket object as returned from socket.listen or
               ssl.wrap_socket if conf specifies cert_file
    """
    bind_addr = get_bind_addr(conf, default_port)

    # TODO(jaypipes): eventlet's greened socket module does not actually
    # support IPv6 in getaddrinfo(). We need to get around this in the
    # future or monitor upstream for a fix
    address_family = [addr[0] for addr in socket.getaddrinfo(bind_addr[0],
                      bind_addr[1], socket.AF_UNSPEC, socket.SOCK_STREAM)
                      if addr[0] in (socket.AF_INET, socket.AF_INET6)][0]

    cert_file = conf.cert_file
    key_file = conf.key_file
    use_ssl = cert_file or key_file
    if use_ssl and (not cert_file or not key_file):
        raise RuntimeError(_("When running server in SSL mode, you must "
                             "specify both a cert_file and key_file "
                             "option value in your configuration file"))

    sock = None
    retry_until = time.time() + 30
    while not sock and time.time() < retry_until:
        try:
            sock = eventlet.listen(bind_addr,
                                   backlog=conf.backlog,
                                   family=address_family)
        except socket.error as err:
            if err.args[0] != errno.EADDRINUSE:
                raise
            eventlet.sleep(0.1)
    if not sock:
        raise RuntimeError(_("Could not bind to %(bind_addr)s"
                             "after trying for 30 seconds")
                           % {'bind_addr': bind_addr})

    return sock


class Server(object):
    """Server class to manage multiple WSGI sockets and applications."""

    def __init__(self, name, conf, threads=1000):
        os.umask(0o27)  # ensure files are created with the correct privileges
        self._logger = logging.getLogger("eventlet.wsgi.server")
        self.name = name
        self.threads = threads
        self.children = set()
        self.stale_children = set()
        self.running = True
        self.pgid = os.getpid()
        self.conf = conf
        try:
            os.setpgid(self.pgid, self.pgid)
        except OSError:
            self.pgid = 0

    def kill_children(self, *args):
        """Kills the entire process group."""
        LOG.error(_LE('SIGTERM received'))
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        self.running = False
        os.killpg(0, signal.SIGTERM)

    def hup(self, *args):
        """Reloads configuration files with zero down time."""
        LOG.error(_LE('SIGHUP received'))
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        raise exception.SIGHUPInterrupt

    def start(self, application, default_port):
        """Run a WSGI server with the given application.

        :param application: The application to run in the WSGI server
        :param default_port: Port to bind to if none is specified in conf
        """

        eventlet.wsgi.MAX_HEADER_LINE = self.conf.max_header_line
        self.application = application
        self.default_port = default_port
        self.configure_socket()
        self.start_wsgi()

    def start_wsgi(self):
        workers = self.conf.workers
        # childs == num of cores
        if workers == 0:
            childs_num = processutils.get_worker_count()
        # launch only one GreenPool without childs
        elif workers == 1:
            # Useful for profiling, test, debug etc.
            self.pool = eventlet.GreenPool(size=self.threads)
            self.pool.spawn_n(self._single_run, self.application, self.sock)
            return
        # childs equal specified value of workers
        else:
            childs_num = workers

        LOG.info(_LI("Starting %d workers"), workers)
        signal.signal(signal.SIGTERM, self.kill_children)
        signal.signal(signal.SIGINT, self.kill_children)
        signal.signal(signal.SIGHUP, self.hup)
        while len(self.children) < childs_num:
            self.run_child()

    def wait_on_children(self):
        while self.running:
            try:
                pid, status = os.wait()
                if os.WIFEXITED(status) or os.WIFSIGNALED(status):
                    self._remove_children(pid)
                    self._verify_and_respawn_children(pid, status)
            except OSError as err:
                if err.errno not in (errno.EINTR, errno.ECHILD):
                    raise
            except KeyboardInterrupt:
                LOG.info(_LI('Caught keyboard interrupt. Exiting.'))
                os.killpg(0, signal.SIGTERM)
                break
            except exception.SIGHUPInterrupt:
                self.reload()
                continue
        eventlet.greenio.shutdown_safe(self.sock)
        self.sock.close()
        LOG.debug('Exited')

    def configure_socket(self, old_conf=None, has_changed=None):
        """Ensure a socket exists and is appropriately configured.

        This function is called on start up, and can also be
        called in the event of a configuration reload.

        When called for the first time a new socket is created.
        If reloading and either bind_host or bind port have been
        changed the existing socket must be closed and a new
        socket opened (laws of physics).

        In all other cases (bind_host/bind_port have not changed)
        the existing socket is reused.

        :param old_conf: Cached old configuration settings (if any)
        :param has changed: callable to determine if a parameter has changed
        """
        # Do we need a fresh socket?
        new_sock = (old_conf is None or (
                    has_changed('bind_host') or
                    has_changed('bind_port')))
        # Will we be using https?
        use_ssl = not (not self.conf.cert_file or not self.conf.key_file)
        # Were we using https before?
        old_use_ssl = (old_conf is not None and not (
                       not old_conf.get('key_file') or
                       not old_conf.get('cert_file')))
        # Do we now need to perform an SSL wrap on the socket?
        wrap_sock = use_ssl is True and (old_use_ssl is False or new_sock)
        # Do we now need to perform an SSL unwrap on the socket?
        unwrap_sock = use_ssl is False and old_use_ssl is True

        if new_sock:
            self._sock = None
            if old_conf is not None:
                self.sock.close()
            _sock = get_socket(self.conf, self.default_port)
            _sock.setsockopt(socket.SOL_SOCKET,
                             socket.SO_REUSEADDR, 1)
            # sockets can hang around forever without keepalive
            _sock.setsockopt(socket.SOL_SOCKET,
                             socket.SO_KEEPALIVE, 1)
            self._sock = _sock

        if wrap_sock:
            self.sock = ssl.wrap_socket(self._sock,
                                        certfile=self.conf.cert_file,
                                        keyfile=self.conf.key_file)

        if unwrap_sock:
            self.sock = self._sock

        if new_sock and not use_ssl:
            self.sock = self._sock

        # Pick up newly deployed certs
        if old_conf is not None and use_ssl is True and old_use_ssl is True:
            if has_changed('cert_file'):
                self.sock.certfile = self.conf.cert_file
            if has_changed('key_file'):
                self.sock.keyfile = self.conf.key_file

        if new_sock or (old_conf is not None and has_changed('tcp_keepidle')):
            # This option isn't available in the OS X version of eventlet
            if hasattr(socket, 'TCP_KEEPIDLE'):
                self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE,
                                     self.conf.tcp_keepidle)

        if old_conf is not None and has_changed('backlog'):
            self.sock.listen(self.conf.backlog)

    def _remove_children(self, pid):
        if pid in self.children:
            self.children.remove(pid)
            LOG.info(_LI('Removed dead child %s'), pid)
        elif pid in self.stale_children:
            self.stale_children.remove(pid)
            LOG.info(_LI('Removed stale child %s'), pid)
        else:
            LOG.warning(_LW('Unrecognised child %s'), pid)

    def _verify_and_respawn_children(self, pid, status):
        if len(self.stale_children) == 0:
            LOG.debug('No stale children')
        if os.WIFEXITED(status) and os.WEXITSTATUS(status) != 0:
            LOG.error(_LE('Not respawning child %d, cannot '
                          'recover from termination'), pid)
            if not self.children and not self.stale_children:
                LOG.info(
                    _LI('All workers have terminated. Exiting'))
                self.running = False
        else:
            if len(self.children) < self.conf.workers:
                self.run_child()

    def stash_conf_values(self):
        """Make a copy of some of the current global CONF's settings.

        Allows determining if any of these values have changed when the config
        is reloaded.
        """
        conf = {}
        conf['bind_host'] = self.conf.bind_host
        conf['bind_port'] = self.conf.bind_port
        conf['backlog'] = self.conf.backlog
        conf['key_file'] = self.conf.key_file
        conf['cert_file'] = self.conf.cert_file
        return conf

    def reload(self):
        """Reload and re-apply configuration settings.

        Existing child processes are sent a SIGHUP signal
        and will exit after completing existing requests.
        New child processes, which will have the updated
        configuration, are spawned. This allows preventing
        interruption to the service.
        """
        def _has_changed(old, new, param):
            old = old.get(param)
            new = getattr(new, param)
            return (new != old)

        old_conf = self.stash_conf_values()
        has_changed = functools.partial(_has_changed, old_conf, self.conf)
        cfg.CONF.reload_config_files()
        os.killpg(self.pgid, signal.SIGHUP)
        self.stale_children = self.children
        self.children = set()

        # Ensure any logging config changes are picked up
        logging.setup(cfg.CONF, self.name)

        self.configure_socket(old_conf, has_changed)
        self.start_wsgi()

    def wait(self):
        """Wait until all servers have completed running."""
        try:
            if self.children:
                self.wait_on_children()
            else:
                self.pool.waitall()
        except KeyboardInterrupt:
            pass

    def run_child(self):
        def child_hup(*args):
            """Shuts down child processes, existing requests are handled."""
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
            eventlet.wsgi.is_accepting = False
            self.sock.close()

        pid = os.fork()
        if pid == 0:
            signal.signal(signal.SIGHUP, child_hup)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            # ignore the interrupt signal to avoid a race whereby
            # a child worker receives the signal before the parent
            # and is respawned unnecessarily as a result
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            # The child has no need to stash the unwrapped
            # socket, and the reference prevents a clean
            # exit on sighup
            self._sock = None
            self.run_server()
            LOG.info(_LI('Child %d exiting normally'), os.getpid())
            # self.pool.waitall() is now called in wsgi's server so
            # it's safe to exit here
            sys.exit(0)
        else:
            LOG.info(_LI('Started child %s'), pid)
            self.children.add(pid)

    def run_server(self):
        """Run a WSGI server."""
        eventlet.wsgi.HttpProtocol.default_request_version = "HTTP/1.0"
        eventlet.hubs.use_hub('poll')
        eventlet.patcher.monkey_patch(all=False, socket=True)
        self.pool = eventlet.GreenPool(size=self.threads)
        socket_timeout = cfg.CONF.eventlet_opts.client_socket_timeout or None
        try:
            eventlet.wsgi.server(
                self.sock,
                self.application,
                custom_pool=self.pool,
                url_length_limit=URL_LENGTH_LIMIT,
                log=self._logger,
                debug=cfg.CONF.debug,
                keepalive=cfg.CONF.eventlet_opts.wsgi_keep_alive,
                socket_timeout=socket_timeout)
        except socket.error as err:
            if err[0] != errno.EINVAL:
                raise
        self.pool.waitall()

    def _single_run(self, application, sock):
        """Start a WSGI server in a new green thread."""
        LOG.info(_LI("Starting single process server"))
        eventlet.wsgi.server(sock, application,
                             custom_pool=self.pool,
                             url_length_limit=URL_LENGTH_LIMIT,
                             log=self._logger,
                             debug=cfg.CONF.debug)


class Middleware(object):
    """Base WSGI middleware wrapper.

    These classes require an application to be initialized that will be called
    next. By default the middleware will simply call its wrapped app, or you
    can override __call__ to customize its behavior.
    """

    def __init__(self, application):
        self.application = application

    def process_request(self, req):
        """Called on each request.

        If this returns None, the next application down the stack will be
        executed. If it returns a response then that response will be returned
        and execution will stop here.
        """
        return None

    def process_response(self, response):
        """Do whatever you'd like to the response."""
        return response

    @webob.dec.wsgify
    def __call__(self, req):
        response = self.process_request(req)
        if response:
            return response
        response = req.get_response(self.application)
        return self.process_response(response)


class Debug(Middleware):
    """Helper class to get information about the request and response.

    Helper class that can be inserted into any WSGI application chain
    to get information about the request and response.
    """

    @webob.dec.wsgify
    def __call__(self, req):
        print(("*" * 40) + " REQUEST ENVIRON")
        for key, value in req.environ.items():
            print(key, "=", value)
        print('')
        resp = req.get_response(self.application)

        print(("*" * 40) + " RESPONSE HEADERS")
        for (key, value) in six.iteritems(resp.headers):
            print(key, "=", value)
        print('')

        resp.app_iter = self.print_generator(resp.app_iter)

        return resp

    @staticmethod
    def print_generator(app_iter):
        """Prints the contents of a wrapper string iterator when iterated."""
        print(("*" * 40) + " BODY")
        for part in app_iter:
            sys.stdout.write(part)
            sys.stdout.flush()
            yield part
        print('')


def debug_filter(app, conf, **local_conf):
    return Debug(app)


class DefaultMethodController(object):
    """Controller that handles the OPTIONS request method.

    This controller handles the OPTIONS request method and any of the HTTP
    methods that are not explicitly implemented by the application.
    """
    def options(self, req, allowed_methods, *args, **kwargs):
        """Return a response that includes the 'Allow' header.

        Return a response that includes the 'Allow' header listing the methods
        that are implemented. A 204 status code is used for this response.
        """
        raise webob.exc.HTTPNoContent(headers=[('Allow', allowed_methods)])

    def reject(self, req, allowed_methods, *args, **kwargs):
        """Return a 405 method not allowed error.

        As a convenience, the 'Allow' header with the list of implemented
        methods is included in the response as well.
        """
        raise webob.exc.HTTPMethodNotAllowed(
            headers=[('Allow', allowed_methods)])


class Router(object):
    """WSGI middleware that maps incoming requests to WSGI apps."""

    def __init__(self, mapper):
        """Create a router for the given routes.Mapper.

        Each route in `mapper` must specify a 'controller', which is a
        WSGI app to call.  You'll probably want to specify an 'action' as
        well and have your controller be a wsgi.Controller, who will route
        the request to the action method.

        Examples:
          mapper = routes.Mapper()
          sc = ServerController()

          # Explicit mapping of one route to a controller+action
          mapper.connect(None, "/svrlist", controller=sc, action="list")

          # Actions are all implicitly defined
          mapper.resource("server", "servers", controller=sc)

          # Pointing to an arbitrary WSGI app.  You can specify the
          # {path_info:.*} parameter so the target app can be handed just that
          # section of the URL.
          mapper.connect(None, "/v1.0/{path_info:.*}", controller=BlogApp())
        """
        self.map = mapper
        self._router = routes.middleware.RoutesMiddleware(self._dispatch,
                                                          self.map)

    @webob.dec.wsgify
    def __call__(self, req):
        """Route the incoming request to a controller based on self.map.

        If no match, return a 404.
        """

        return self._router

    @staticmethod
    @webob.dec.wsgify
    def _dispatch(req):
        """Returns controller after matching the incoming request to a route.

        Called by self._router after matching the incoming request to a route
        and putting the information into req.environ. Either returns 404 or the
        routed WSGI app's response.
        """
        match = req.environ['wsgiorg.routing_args'][1]
        if not match:
            return webob.exc.HTTPNotFound()
        app = match['controller']
        return app


class Request(webob.Request):
    """Add some OpenStack API-specific logic to the base webob.Request."""

    def best_match_content_type(self):
        """Determine the requested response content-type."""
        supported = ('application/json',)
        bm = self.accept.best_match(supported)
        return bm or 'application/json'

    def get_content_type(self, allowed_content_types):
        """Determine content type of the request body."""
        if "Content-Type" not in self.headers:
            raise exception.InvalidContentType(content_type=None)

        content_type = self.content_type


        if content_type not in allowed_content_types:
            raise exception.InvalidContentType(content_type=content_type)
        else:
            return content_type

    def best_match_language(self):
        """Determines best available locale from the Accept-Language header.

        :returns: the best language match or None if the 'Accept-Language'
                  header was not available in the request.
        """
        if not self.accept_language:
            return None
        all_languages = i18n.get_available_languages('knob')
        return self.accept_language.best_match(all_languages)


def is_json_content_type(request):
    if request.method == 'GET':
        try:
            aws_content_type = request.params.get("ContentType")
        except Exception:
            aws_content_type = None
        # respect aws_content_type when both available
        content_type = aws_content_type or request.content_type
    else:
        content_type = request.content_type
    # bug #1887882
    # for back compatible for null or plain content type
    if not content_type or content_type.startswith('text/plain'):
        content_type = 'application/json'
    if (content_type in ('JSON', 'application/json')
            and request.body.startswith(b'{')):
        return True
    return False


class JSONRequestDeserializer(object):
    def has_body(self, request):
        """Returns whether a Webob.Request object will possess an entity body.

        :param request:  Webob.Request object
        """
        if (int(request.content_length or 0) > 0 and
                is_json_content_type(request)):
            return True

        return False

    def from_json(self, datastring):
        try:
            if len(datastring) > cfg.CONF.max_json_body_size:
                msg = _('JSON body size (%(len)s bytes) exceeds maximum '
                        'allowed size (%(limit)s bytes).'
                        ) % {'len': len(datastring),
                             'limit': cfg.CONF.max_json_body_size}
                raise exception.RequestLimitExceeded(message=msg)
            return jsonutils.loads(datastring)
        except ValueError as ex:
            raise webob.exc.HTTPBadRequest(six.text_type(ex))

    def default(self, request):
        if self.has_body(request):
            return {'body': self.from_json(request.body)}
        else:
            return {}


class Resource(object):
    """WSGI app that handles (de)serialization and controller dispatch.

    Reads routing information supplied by RoutesMiddleware and calls
    the requested action method upon its deserializer, controller,
    and serializer. Those three objects may implement any of the basic
    controller action methods (create, update, show, index, delete)
    along with any that may be specified in the api router. A 'default'
    method may also be implemented to be used in place of any
    non-implemented actions. Deserializer methods must accept a request
    argument and return a dictionary. Controller methods must accept a
    request argument. Additionally, they must also accept keyword
    arguments that represent the keys returned by the Deserializer. They
    may raise a webob.exc exception or return a dict, which will be
    serialized by requested content type.
    """
    def __init__(self, controller, deserializer, serializer=None):
        """Initialisation of the WSGI app.

        :param controller: object that implement methods created by routes lib
        :param deserializer: object that supports webob request deserialization
                             through controller-like actions
        :param serializer: object that supports webob response serialization
                           through controller-like actions
        """
        self.controller = controller
        self.deserializer = deserializer
        self.serializer = serializer

    @webob.dec.wsgify(RequestClass=Request)
    def __call__(self, request):
        """WSGI method that controls (de)serialization and method dispatch."""
        action_args = self.get_action_args(request.environ)
        action = action_args.pop('action', None)

        # From reading the boto code, and observation of real AWS api responses
        # it seems that the AWS api ignores the content-type in the html header
        # Instead it looks at a "ContentType" GET query parameter
        # This doesn't seem to be documented in the AWS cfn API spec, but it
        # would appear that the default response serialization is XML, as
        # described in the API docs, but passing a query parameter of
        # ContentType=JSON results in a JSON serialized response...
        content_type = request.params.get("ContentType")

        try:
            deserialized_request = self.dispatch(self.deserializer,
                                                 action, request)
            action_args.update(deserialized_request)
    
            LOG.debug(('Calling %(controller)s : %(action)s'),
                      {'controller': self.controller, 'action': action})
            action_result = self.dispatch(self.controller, action,
                                          request, **action_args)
        except TypeError as err:
            LOG.error(_LE('Exception handling resource: %s'), err)
            msg = _('The server could not comply with the request since '
                    'it is either malformed or otherwise incorrect.')
            err = webob.exc.HTTPBadRequest(msg)
            http_exc = translate_exception(err, request.best_match_language())
            # NOTE(luisg): We disguise HTTP exceptions, otherwise they will be
            # treated by wsgi as responses ready to be sent back and they
            # won't make it into the pipeline app that serializes errors
            raise exception.HTTPExceptionDisguise(http_exc)
        except webob.exc.HTTPException as err:
            if not isinstance(err, webob.exc.HTTPError):
                # Some HTTPException are actually not errors, they are
                # responses ready to be sent back to the users, so we don't
                # error log, disguise or translate those
                raise
            if isinstance(err, webob.exc.HTTPServerError):
                LOG.error(
                    _LE("Returning %(code)s to user: %(explanation)s"),
                    {'code': err.code, 'explanation': err.explanation})
            http_exc = translate_exception(err, request.best_match_language())
            raise exception.HTTPExceptionDisguise(http_exc)
        except exception.KnobException as err:
            raise translate_exception(err, request.best_match_language())
        except Exception as err:
            log_exception(err, sys.exc_info())
            raise translate_exception(err, request.best_match_language())
        # Here we support either passing in a serializer or detecting it
        # based on the content type.
        try:
            serializer = self.serializer
            if serializer is None:
                if content_type == "JSON":
                    serializer = serializers.JSONResponseSerializer()
                else:
                    serializer = serializers.XMLResponseSerializer()

            response = webob.Response(request=request)
            self.dispatch(serializer, action, response, action_result)
            return response

        # return unserializable result (typically an exception)
        except Exception:
            # Here we should get API exceptions derived from knobAPIException
            # these implement get_unserialized_body(), which allow us to get
            # a dict containing the unserialized error response.
            # We only need to serialize for JSON content_type, as the
            # exception body is pre-serialized to the default XML in the
            # knobAPIException constructor
            # If we get something else here (e.g a webob.exc exception),
            # this will fail, and we just return it without serializing,
            # which will not conform to the expected AWS error response format
            if content_type == "JSON":
                try:
                    err_body = action_result.get_unserialized_body()
                    serializer.default(action_result, err_body)
                except Exception:
                    LOG.warning(_LW("Unable to serialize exception "
                                    "response"))

            return action_result

    def dispatch(self, obj, action, *args, **kwargs):
        """Find action-specific method on self and call it."""
        try:
            method = getattr(obj, action)
        except AttributeError:
            method = getattr(obj, 'default')
        return method(*args, **kwargs)

    def get_action_args(self, request_environment):
        """Parse dictionary created by routes library."""
        try:
            args = request_environment['wsgiorg.routing_args'][1].copy()
        except Exception:
            return {}

        try:
            del args['controller']
        except KeyError:
            pass

        try:
            del args['format']
        except KeyError:
            pass

        return args


def log_exception(err, exc_info):
    args = {'exc_info': exc_info} if cfg.CONF.verbose or cfg.CONF.debug else {}
    LOG.error(_LE("Unexpected error occurred serving API: %s"), err,
              **args)


def translate_exception(exc, locale):
    """Translates all translatable elements of the given exception."""
    if isinstance(exc, exception.KnobException):
        exc.message = i18n.translate(exc.message, locale)
    else:
        err_msg = encodeutils.exception_to_unicode(exc)
        exc.message = i18n.translate(err_msg, locale)

    if isinstance(exc, webob.exc.HTTPError):
        exc.explanation = i18n.translate(exc.explanation, locale)
        exc.detail = i18n.translate(getattr(exc, 'detail', ''), locale)
    return exc


@six.add_metaclass(abc.ABCMeta)
class BasePasteFactory(object):
    """A base class for paste app and filter factories.

    Sub-classes must override the KEY class attribute and provide
    a __call__ method.
    """

    KEY = None

    def __init__(self, conf):
        self.conf = conf

    @abc.abstractmethod
    def __call__(self, global_conf, **local_conf):
        return

    def _import_factory(self, local_conf):
        """Import an app/filter class.

        Lookup the KEY from the PasteDeploy local conf and import the
        class named there. This class can then be used as an app or
        filter factory.

        Note we support the <module>:<class> format.

        Note also that if you do e.g.

          key =
              value

        then ConfigParser returns a value with a leading newline, so
        we strip() the value before using it.
        """
        class_name = local_conf[self.KEY].replace(':', '.').strip()
        return importutils.import_class(class_name)


class AppFactory(BasePasteFactory):
    """A Generic paste.deploy app factory.

    This requires knob.app_factory to be set to a callable which returns a
    WSGI app when invoked. The format of the name is <module>:<callable> e.g.

      [app:apiv1app]
      paste.app_factory = knob.common.wsgi:app_factory
      knob.app_factory = knob.api.cfn.v1:API

    The WSGI app constructor must accept a ConfigOpts object and a local config
    dict as its two arguments.
    """

    KEY = 'knob.app_factory'

    def __call__(self, global_conf, **local_conf):
        """The actual paste.app_factory protocol method."""
        factory = self._import_factory(local_conf)
        return factory(self.conf, **local_conf)


class FilterFactory(AppFactory):
    """A Generic paste.deploy filter factory.

    This requires knob.filter_factory to be set to a callable which returns a
    WSGI filter when invoked. The format is <module>:<callable> e.g.

      [filter:cache]
      paste.filter_factory = knob.common.wsgi:filter_factory
      knob.filter_factory = knob.api.middleware.cache:CacheFilter

    The WSGI filter constructor must accept a WSGI app, a ConfigOpts object and
    a local config dict as its three arguments.
    """

    KEY = 'knob.filter_factory'

    def __call__(self, global_conf, **local_conf):
        """The actual paste.filter_factory protocol method."""
        factory = self._import_factory(local_conf)

        def filter(app):
            return factory(app, self.conf, **local_conf)

        return filter


def setup_paste_factories(conf):
    """Set up the generic paste app and filter factories.

    Set things up so that:

      paste.app_factory = knob.common.wsgi:app_factory

    and

      paste.filter_factory = knob.common.wsgi:filter_factory

    work correctly while loading PasteDeploy configuration.

    The app factories are constructed at runtime to allow us to pass a
    ConfigOpts object to the WSGI classes.

    :param conf: a ConfigOpts object
    """
    global app_factory, filter_factory
    app_factory = AppFactory(conf)
    filter_factory = FilterFactory(conf)


def teardown_paste_factories():
    """Reverse the effect of setup_paste_factories()."""
    global app_factory, filter_factory
    del app_factory
    del filter_factory


def paste_deploy_app(paste_config_file, app_name, conf):
    """Load a WSGI app from a PasteDeploy configuration.

    Use deploy.loadapp() to load the app from the PasteDeploy configuration,
    ensuring that the supplied ConfigOpts object is passed to the app and
    filter constructors.

    :param paste_config_file: a PasteDeploy config file
    :param app_name: the name of the app/pipeline to load from the file
    :param conf: a ConfigOpts object to supply to the app and its filters
    :returns: the WSGI app
    """
    setup_paste_factories(conf)
    try:
        return deploy.loadapp("config:%s" % paste_config_file, name=app_name)
    finally:
        teardown_paste_factories()
