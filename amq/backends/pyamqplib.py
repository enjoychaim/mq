"""`amqplib`_ backend for amq.
"""
from amqplib import client_0_8 as amqp
from amqplib.client_0_8.exceptions import AMQPChannelException
from amq.backends.base import BaseMessage, BaseBackend
import itertools
import warnings

DEFAULT_PORT = 5672


class QueueAlreadyExistsWarning(UserWarning):
    """a queue with that name already exists, so a recently changed
    ``routing_key`` or other settings might be ignored unless you
    rename the queue or restart the broker."""


class Message(BaseMessage):
    """a message received by the broker.
    """

    def __init__(self, backend, amqp_message, **kwargs):
        self._amqp_message = amqp_message
        self.backend = backend

        for attr_name in ("body",
                          "delivery_tag",
                          "content_type",
                          "content_encoding",
                          "delivery_info"):
            kwargs[attr_name] = getattr(amqp_message, attr_name, None)

        super(Message, self).__init__(backend, **kwargs)


class Backend(BaseBackend):
    """amqplib backend
    """

    default_port = DEFAULT_PORT

    Message = Message

    def __init__(self, connection, **kwargs):
        self.connection = connection
        self.default_port = kwargs.get("default_port", self.default_port)
        self._channel = None

    @property
    def channel(self):
        """If no channel exists, a new one is requested."""
        if not self._channel:
            self._channel = self.connection.get_channel()
        return self._channel

    def establish_connection(self):
        """Establish connection to the AMQP broker."""
        conninfo = self.connection
        if not conninfo.port:
            conninfo.port = self.default_port
        return amqp.Connection(host=conninfo.host,
                               userid=conninfo.userid,
                               password=conninfo.password,
                               virtual_host=conninfo.virtual_host,
                               insist=conninfo.insist,
                               ssl=conninfo.ssl,
                               connect_timeout=conninfo.connect_timeout)

    def close_connection(self, connection):
        """Close the AMQP broker connection."""
        connection.close()

    def queue_exists(self, queue):
        try:
            # if passive=True, the server will not create the queue, just check
            self.channel.queue_declare(queue=queue, passive=True)
        except AMQPChannelException as e:
            if e.amqp_reply_code == 404:
                return False
            raise e
        else:
            return True

    def queue_purge(self, queue, **kwargs):
        """Discard all messages in the queue. This will delete the messages
        and results in an empty queue."""
        return self.channel.queue_purge(queue=queue)

    def queue_declare(self, queue, durable, exclusive, auto_delete,
                      warn_if_exists=False):
        """Declare a named queue."""

        if warn_if_exists and self.queue_exists(queue):
            warnings.warn(QueueAlreadyExistsWarning(
                QueueAlreadyExistsWarning.__doc__))

        return self.channel.queue_declare(queue=queue,
                                          durable=durable,
                                          exclusive=exclusive,
                                          auto_delete=auto_delete)

    def exchange_declare(self, exchange, type, durable, auto_delete):
        """Declare an named exchange."""
        return self.channel.exchange_declare(exchange=exchange,
                                             type=type,
                                             durable=durable,
                                             auto_delete=auto_delete)

    def queue_bind(self, queue, exchange, routing_key):
        """Bind queue to an exchange using a routing key."""
        return self.channel.queue_bind(queue=queue,
                                       exchange=exchange,
                                       routing_key=routing_key)

    def message_to_python(self, raw_message):
        return self.Message(backend=self, amqp_message=raw_message)

    def get(self, queue, no_ack=False):
        """Receive a message from a declared queue by name.
        :returns: A :class:`Message` object if a message was received,
            ``None`` otherwise. If ``None`` was returned, it probably means
            there was no messages waiting on the queue.
        """
        raw_message = self.channel.basic_get(queue, no_ack=no_ack)
        if not raw_message:
            return None
        return self.message_to_python(raw_message)

    def declare_consume(self, queue, no_ack, callback, consumer_tag):
        return self.channel.basic_consume(queue=queue,
                                          no_ack=no_ack,
                                          callback=callback,
                                          consumer_tag=consumer_tag)

    def declare_consumer(self, queue, no_ack, callback, consumer_tag, nowait=False):
        """Declare a consumer."""
        self.channel.basic_consume(queue=queue,
                                   no_ack=no_ack,
                                   callback=callback,
                                   consumer_tag=consumer_tag,
                                   nowait=nowait)

    def consume(self, limit=None):
        """Returns an iterator that waits for one message at a time,
        calling the callback when messages arrive."""
        for total_message_count in itertools.count():
            if limit and total_message_count >= limit:
                raise StopIteration
            self.channel.wait()
            yield True

    def cancel(self, consumer_tag):
        """Cancel a channel by consumer tag."""
        if not self.channel.connection:
            return
        self.channel.basic_cancel(consumer_tag)

    def close(self):
        """Close the channel if open."""
        if getattr(self, "channel") and self.channel.is_open:
            self.channel.close()

    def ack(self, delivery_tag):
        """Acknowledge a message by delivery tag."""
        return self.channel.basic_ack(delivery_tag)

    def reject(self, delivery_tag):
        """Reject a message by deliver tag."""
        return self.channel.basic_reject(delivery_tag, requeue=False)

    def requeue(self, delivery_tag):
        """Reject and requeue a message by delivery tag."""
        return self.channel.basic_reject(delivery_tag, requeue=True)

    def prepare_message(self, message_data, delivery_mode, priority=None,
                        content_type=None, content_encoding=None):
        """Encapsulate data into a AMQP message."""
        message = amqp.Message(message_data, priority=priority,
                               content_type=content_type,
                               content_encoding=content_encoding)
        message.properties["delivery_mode"] = delivery_mode
        return message

    def publish(self, message, exchange, routing_key, mandatory=None,
                immediate=None):
        """Publish a message to a named exchange."""
        return self.channel.basic_publish(message, exchange=exchange,
                                          routing_key=routing_key,
                                          mandatory=mandatory,
                                          immediate=immediate)