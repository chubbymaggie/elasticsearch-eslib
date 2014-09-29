# elasticsearch-eslib

2014.09.29 -- Hans Terje Bakke

Python library for document processing for Elasticsearch.

While Elasticsearch is what we originally created it for, it is fully usable for anything else as well.
The only limitation is that a lot of the processing stages are using an Elasticsearch-like document format.
But this can easily be converted to something else. For example, a SolrWriter could take an "esdoc" as input
and write it to Solr. The "esdoc" in this case is simply a JSON compatible Python dict type with the following
meta fields, that may even be omitted in many cases, and that you can make whatever you want of:

```json
{
    "_index"  : "(some kind of document cluster, like DB table, search index, etc.)"
    "_type"   : "(document type in some data store)",
    "_id"     : "(document id)",
    "_source" : {
        (document fields and data go here...)
    }
}
```

## Introduction

A 'processor' processes incoming data and generates output.

It can also generate its own data or fetch from external data sources and services.
Instead, or in addition to, writing output to its own 'sockets', it can also write data
to external data sources and services. In these cases it is commonly referred to as a 'generator',
and has its own execution thread.

A processor has one or more input 'connectors' that can connect to one more output 'sockets'.
Connectors and sockets (commonly called 'terminals') are registered with an optional 'protocol' tag.
If it exists, an attempted connection will check if the data protocol is the same in both connector
and socket.

A processor B is said to 'subscribe' to output from processor A if it has a connector connected a
socket on A. In this case, A has the role of 'producer' (to B) and B has the role of 'subscriber' (to A).

## Usage

From a Python script, we can create a processing graph as in this example:

```python
a = ElasticsearchReader()
b = ElasticsearchWriter()
a.config.index = "employees"
b.config.index = "employees_copy"
b.subscribe(a)
```
    
and execute it with

```python
a.start()
```

In this simple example, the first processor is a generator, and the entire pipeline will finish when 'a'
completes. The simple "b.subscribe(a)" is possible because there is only one connector in 'b' and only
one socket in 'a'. Otherwise, we would have to specify the connector and socket names.

By default, a processor that is stopped either explicitly from outside, or completes generating data (as
in this example), will send a stop signal to its subscribers. This is not always a desirable behaviour.
Say we had 20 readers sending data to 1 writer. We would not like the writer to stop when the first reader
completes. To avoid this, we can use

```python
...
b.keepalive = True
a.start()
time.sleep(10)  # The reader is still working in its own thread
b.put(mydoc)    # Writes to the only connector ("input", of protocol "esdoc")
a.wait()        # Wait for a to complete/stop
b.stop()        # ... then explicitly stop b
```

One processor/connector can subscribe to data from many processors/sockets. One processor can have many
different named connectors, expecting data in various formats (hinted by its 'protocol' tag.) And a processor/socket
can have many processors/connectors subscribing to data it outputs.

### Behind the scene

Technically, a processor sends document data to its sockets. The sockets send documents to its connected connectors.
A connector has a queue of incoming items, and a thread that pulls documents off the queue and sends it to
a processing method in the processor class. This method processes the data and sends the result to one or
more of its sockets, which again send to connected connectors...

A generator style processor has another thread that generates documents somehow, and sends it to its socket(s).

### Listen to output

Analogous with the processor.put(doc) command, you might also want to listen to output from a processor in your
program. You can do this by adding a 'callback' for the socket. For example like this

```python
output = []
processor.add_callback(lambda doc: output.append(doc), socket_name)
...
processor.start()
processor.wait()
print output
```

or instead of the lambda function, use a method that takes a document as an argument, e.g.:

```python
def do_stuff(document):
    print "I spy with my little eye, a document containing:", document

...
processor.add_callback(do_stuff)
...
```

### Protocol compliance

When sockets and connector are joined ("connected"), there is a check for protocol compliance. These are string
tags using a dot-notation for specializations. A terminal is registered with 'any' if it doesn't care about the
protocol. Explanation by some examples:

```text
SOCKET PROTOCOL          CONNECTOR PROTOCOL        WILL MATCH?
---------------          ------------------        -----------
seating.chair            seating.chair             yes (of course)
seating.chair.armchair   seating                   yes, connector accepts any seating
seating                  seating.chair.armchair    no, connector expects armchairs, specifically
any                      string                    yes (but, consumer: beware! it might be anything!)
string                   any                       yes, we accept anything
```

### Members for using the Processor (and derivates)

```text
Read/write:
    keepalive
Read only:
    accepting
    stopping
    running
    suspended
    aborted
Methods:
    __init__(name) # Constructor/init
    subscribe(producer=None, socket_name=None, connector_name=None)
    unsubscribe(producer=None, socket_name=None, connector_name=None)
    attach(subscriber, socket_name=None, connector_name=None)
    detach(subscriber, socket_name=None, connector_name=None)
    connector_info(*args)  # returns list
    socket_info(*args)     # returns list
    start()
    stop()
    abort()
    suspend()
    resume()
    wait()
    put(document, connector_name=None)
    add_callback(method, socket_name=None)
Methods for debugging:
    DUMP
    DUMP_connectors
    DUMP_sockets
```
        
## Writing your own Processor

The simple processor (not Generator type) typically has one or more connectors. A connector receives data from
a socket, or from a "processor.put(document, connector_name)" statement (which in turn puts the data on the
connector queue). Internally, a connector has a queue and is running a its own thread that pulls items off the
queue and executes whatever method is registered with the connector.

Any object passed to such a method is considered to be read-only. You *may* alter it, preferably only add to it.
But it is generally a bad idea, since many processors could potentially receive the same object. If you want to
pass it on to a socket as-is, that's fine. And it is the best performance wise. But if you need to alter it,
you should consider creating a deep or shallow clone. Shallow clones are fine if you just want to change one
part of the object and refer to the rest as it is.

As a general rule of thumb you should never alter the state members yourself directly. If you want to have
the processor stop or abort itself, you should call "self.stop()" or "self.abort()".

### A simple processor

Let's start with a simple processor that receives input on a connector and writes its processed output to a socket.
Let's make a processor that reverses and optionally swaps the casing of a string.

```python
from eslib import Processor

class StringReverser(Processor):

    def __init__(self, name=None):
        super(StringReverser, self).__init__(name)
        
        self.config.swapcase = False
```
        
Notice the "swapcase" config variable. "config" is a predefined empty class that is instantiated. Simply for
easier containment of config variables.

In this case we will set "swapcase" if we want to swap the casing of the string we are reversing.

We also create a connector for the input and two sockets for the output. One is a pure pass-through while the
other provides the modified output:

```python
        self.create_connector(self._incoming, "input", "str")
        self.create_socket("original", "str")
        self.create_socket("modified", "str")
```

We use "str" as a protocol tag. This is not the same as a Python type; it is simply a hint. When connecting
sockets and connectors there is check for protocol compliance. If you want to expect or spew out anything, simply
specify None or omit the protocol specification.

The following member methods are called when the processor starts or stops (including getting aborted),
respectively:

```python
    def on_open(self):  pass  # Before threads are spun up.
    def on_abort(self): pass  # After call to abort(), but before closing with on_close()
    def on_close(self): pass  # Final call after stopping/aborting processor; always called
```

This is typically used for opening and closing files, establishing remote connections, resetting counters, etc.

For this example, there is nothing special we want to do when starting and stopping. (Really, starting the
processor in this case simply spins up the connector, that will deliver documents to our "_incoming(document)"
method as soon as it can. So now on to this method:

```python
    def _incoming(self, document):
        # TODO: You might want to check if the document is indeed a 'str' or 'unicode' here...
        
        s = document[::-1]  # Reverse the string of characters
        if self.config.swapcase:
            s = s.swapcase()
        
        # Write to the sockets:
        self.sockets["original"].send(document)  # Incoming document, unmodified
        self.sockets["modified"].send(s)
```

Often, processing can be quite heavy stuff, and quite unnecessary to do a lot of work with producing output if
there are no consumers. Therefore, you might want to first check if there is actually any consumers expecting
output either for the entire processor or per socket, with

```python
        if not self.has_output:
            return
            
        # or
        
        if self.sockets["modified"].has_output:
            # calculate and send the stuff...
```

### Useful members for implementing simple Processors

```text
    Methods for you to implement:
        __init__(name=None)    # constructor; remember to call super(your_class, self).__init__(name)
        on_open()              # called before starting execution threads
        on_abort()             # called after a processor receives a call to abort(), but before on_close()
        on_close()             # called when the processor has stopped or aborted
    Read-only properties and variables:
        name                   # name of the processor
        config                 # object containing  all configuration data for the processor
        connectors             # dict
        sockets                # dict
        has_output             # bool; indicating whether there are sockets with connections
        log                    # logger; log processor events here
        doclog                 # logger; log problems with documents here
    Methods to call:
        create_connector(method, name=None, protocol=None, description=None)
        create_socket(name=None, description=None)
        stop()                 # call this if you want to explicitly stop prematurely
        abort()                # call this if you want to explicitly abort prematurely
    Properties and methods on sockets:
        socket.has_output      # bool; indicating whether the socket has connections (subscribers)
        socket.send(document)  # sends document to connected subscribers for asynchronous processing
```

### Processor lifespan

A simple processor typically sits in between other processors in a pipeline or graph. They are started by
another processor earlier in the chain, and they are instructed to stop when a processor they are subscribing to
stops. So a processor C subscribing to A or B will stop if one of the other stops. Unless it is flagged with
"keepalive = True".

When stopping, the processor closes all its connectors for further input (by setting "connector.accept = False").
The connectors will then continue to work off their queues until empty, and then the processor are finally
stopped. For immediate termination without processing whatever is still queued up, an "abort()" must be called.

### Generators and Monitors

A 'Generator' is a Processor that is expected to produce its output mainly from other sources than what is coming
in through connectors. It has its own execution thread. For example, a FileWriter is a simple processor that
writes whatever it gets on its connector to a file. A FileReader has its own worker thread that reads lines from
files and generates documents as its output, and therefor implements Generator. An ElasticsearchWriter is a
Generator because it needs its own worker thread to gather up incoming documents and send them in batches to the
server for higher performance. So although they have the file and Elasticsearch writers have similar purposes,
they have different implementation schemes.

### Generator and Monitor lifespan

The Generator typically lives until it has consumed everything it was supposed to, such as reading parts of an
index, reading files, etc. Then it calls "stop()" on itself and its worker loop finishes.

A 'Monitor' implements Generator. The semantic difference is that the Monitor does not finish unless explicitly
stopped. It typically monitors an eternal stream of incoming data, for example tweets from Twitter or anything
from a message queueing system such as RabbitMQ.

### Additional useful members for implementing Generators and Monitors

```text
Read-only properties and variables:
    accepting
    stopping
    running
    suspended
    aborted
    end_tick_reason        # True if there is a reason to exit on_tick; either 'aborted', 'stopping' or
                           #   not 'running'; but (obs!!) it does not consider 'suspended'
Variables for you to update (if you like..):
    total                  # typically total number of docs to generate (total DB entries, for example)
    count                  # typically number of docs generated so far (e.g. to see progress towards total)
Methods for you to implement:
    on_startup()           # called at beginning of worker thread; on_open has already been called
    on_shutdown()          # called when stopping, but before stopped; your chance to finish up
    on_tick()              # called by worker thread; do all or parts of your stuff in here
    on_suspend()
    on_resume()
    on_abort()             # see comment, below
```

I'll go through the typical of these event handlers one by one, including the on_open() and on_close() methods,
in order of lifecycle chronological order.

#### on_open()

This is called when the processor starts, but before the worker thread starts.
Config verification, existence of external resources, etc, could be verified here.
Be aware that the processor should be able to start and stop and start again multiple times,
so lingering TCP connections, locked files, your own performance counters and state variables,
etc, must be accounted for.

#### on_startup()

This is called after the worker thread has started, but before we enter the run loop. This is
another place for initialization logic. What you do here might as well have been placed in on_open(),
but not vice versa. This is typically not the place to verify config variables. Do that in on_open(). 
But this is a logical place to host the code that is the reverse of the "shutdown" code.

#### on_tick()

This is the tricky one...

The simplest way is to have setup and shutdown done outside the tick, and handle small pieces each time
you get a call to this method. Pretty much all the time, unless suspended. This way you will not have to handle
the 'suspended' status, either.

If you want to handle everything yourself, you need to check the 'suspended' status, and whether it is time to
stop handling the tick, summarized in the boolean property 'end_tick_reason'. Here are three different examples
of how this is handled:

ElasticsearchReader: This does both setup and cleanup from inside on_tick(). It checks for 'end_tick_reason'
and sleeps while suspended.

RabbitmqMonitor: Starts listening from on_startup(). It processes as much as it can get from the queue in on_tick()
and also handles reconnect attempts there if necessary. Then it returns to the run loop in the generator.
Stop and abort events call the pika API and tells it to cancel further consumption so the on_tick loop does
not need to handle this. Suspension is also handled between the "ticks", but we need to cancel and restart
consumption between suspend/resume events.

FileReader: The file reader can read from one or more files, one entire file or one line per file generating
a document (configurable behaviour). It relies on a revisit to the on_tick() method for each new file that
needs to be processed, and opens the new file and starts reading. It burns through files a line at a time if
so configured, but it also checks whether there is an 'end_tick_reason' or a 'suspend'. In which case it
returns to the main run loop, only to be revisited later to pick up reading from where it was. Any potentially
open file (due to a premature stop() or abort()) is closed in on_close().

#### on_suspend() / on_resume()

In case you want to do something special when suspend or resume has happened. Most often you would probably
just watch the 'suspended' status in the on_tick() method instead.

#### on_shutdown()

When the generator receives a stop() command, it enters 'stopping' mode before it actually stops. This method
is called when the generator is stopping. (If you handle the stopping status yourself inside the on_tick()
method, then you do not have to handle it here.)

After this method exits, the generator registeres that production has stopped from this worker thread.
Is still 'stopping', however, until all connector queues finished processing and are empty. Only then is the
processor truly considered to be finished, and the worker thread exits.

The next and final event call will now be to on_close().

#### on_abort()

This is called after all processing is supposed to have stopped, after leaving the on_tick() method. But the
thread is still running, but will be terminated right after this method is called. Whether you clean up in
on_abort() or on_close() doesn't matter much most of the time. But it can be used to separate normal shutdown
logic from abortion logic and keep the common code in on_close().

#### on_close()

This is called after the worker thread and all process requests from connectors have stopped.
Consider this the final operation, but be aware that the processor can be restarted, so all must be
cleaned up and ready to go again.

### Ad-hoc Processor

Say you have a processor "p1" and "p2" that pass a string (here tagged with protocol "str") from one to the other,
and you want to reverse that string with a processor in the middle, but you don't want to bother with making
another class. This is how you do it:

```python
p1 = ...
p2 = ...

def reverse(document):
    socket = send(document[::-1]

middle = Processor("ad-hoc")
middle.create_connector(reverse, "input", protocol="str")
socket = middle.create_socket("output", protocol="str")

p1.attach(middle.attach(p2))
p1.start()
p2.wait()
```

### A word on multiple inheritance

Multiple inheritance in Python can be nice (and fun :-)). I often find it handy to pull out common code and use multiple
inheritance when the two derived classes I have do not need to share the same base class, just parts of it.

For example my RabbitmqMonitor is a 'Generator', while my RabbitmqWriter is a 'Processor'. Apart from that,
they should share some common Rabbitmq code. So far all is well.

But I also want to set the common config variables in the constructor for the common code (in RabbitmqBase).
But the self.config is created in Processor, which RabbbitmqBase does not inherit, although I assume it exists
in the RabbitmqBase constructor. It feels a little "spaghettish", but it works just fine as long as the
inheriting classes have called the Processor/Generator constructor first. In other words...:


```python
class Config:
    pass

class Processor(object):
    def __init__(self, name):
        self.config = Config()
        ...
    
class Generator(Processor):
    def __init__(self, name):
        super(Generator, self).__init__(name)
        ...

class RabbitmqBase(object):
    def __init__(self):
        # NOTE: Assumes the existence of self.config from other inherited object (Processor or Generator)
        self.config.host         = "localhost"
        self.config.port         = 5672
        self.config.admin_port   = 15672
        ...

class RabbitmqMonitor(Generator, RabbitmqBase):
    def __init__(self, name=None):
        Generator.__init__(self, name)
        RabbitmqBase.__init__(self)
        ...

class RabbitmqWriter(Processor, RabbitmqBase):
    def __init__(self, name=None):
        Processor.__init__(self, name)
        RabbitmqBase.__init__(self)
        ...
```
