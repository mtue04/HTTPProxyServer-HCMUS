import socket
import sys, os
import _thread as thread
import datetime, time

# global variables
MAX_CONNECTIONS = 10
BUFFER_SIZE = 4096
CACHE_DIRECTORY = "cache"
CONFIG_FILE = "config.conf"
image_extensions = [    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp', 
                        '.raw', '.heic', '.pdf', '.ai', '.ico', '.tif', '.psd'     ]
cache = {}  # Dictionary to store the cached images and their expiration times         

#-------------------------  SUPPORTER FUNCTIONS  -------------------------#

# Read config file
def read_config(filename):
    config = {}
    
    with open(filename, 'r') as file:
        lines = file.readlines()
        
        for line in lines:
            line = line.strip()
            if line:
                key, value = line.split('=')
                config[key.strip()] = value.strip()
    
    cache_time = int(config.get('cache_time', 0))
    whitelisting = set(map(str.strip, config.get('whitelisting', '').split(',')))
    time_restriction = config.get('time', '')

    return {
        'cache_time': cache_time,
        'whitelisting': whitelisting,
        'time_restriction': time_restriction
    }

config_values = read_config(CONFIG_FILE)
cache_expiration_time = config_values['cache_time']
whitelisting = list(config_values['whitelisting'])
time_restriction = config_values['time_restriction']

# Check whether time is in allowed time
def is_allowed_time(time_restriction):
    now = datetime.datetime.now()
    current_time = now.time()
    
    if "-" in time_restriction:
        start_time_str, end_time_str = time_restriction.split("-")
        start_time = datetime.datetime.strptime(start_time_str, "%H").time()
        end_time = datetime.datetime.strptime(end_time_str, "%H").time()
        
        if start_time <= current_time <= end_time:
            return True
    else:
        return False

# Check whether website is in whitelisting
def get_domain_from_url(url):
    # Delete 'http://'
    if url.startswith("http://"):
        url = url[len("http://"):]

    # Find index of the first '/' after domain
    slash_index = url.find("/")
    if slash_index != -1:
        domain = url[:slash_index]
    else:
        domain = url

    return domain

def is_whitelisting(domain, whitelisting):
    for allowed_domain in whitelisting:
        if domain in allowed_domain:
            return True
    return False

# Response Error 403
def serve_403_response(tcpCliSock):
    response = "HTTP/1.1 403 Forbidden\r\nContent-Type: text/html\r\n\r\n"

    # PATH to Error 403 HTML file
    index_path = r"index.html"

    try:
        with open(index_path, "rb") as index_file:
            response_content = index_file.read()
            response += response_content.decode("latin1")
    except Exception as e:
        response += "<html><body><h1>Error 403: Forbidden</h1></body></html>"

    tcpCliSock.sendall(response.encode())
    tcpCliSock.close()

#-------------------------  HANDLE CACHE IMAGE  -------------------------#

if not os.path.exists(CACHE_DIRECTORY):
    os.makedirs(CACHE_DIRECTORY)
    
def load_file(file_path, mode="rb"):
    try:
        with open(file_path, mode) as file:
            content = file.read()
            return content
    except FileNotFoundError:
        return None

# Parse the request to get the server_url, request_target
def parse_request(request):
    first_line_tokens = request.split('\r\n')[0].split(' ')
    server_url = first_line_tokens[1].split('/')[2]
    path_pos = first_line_tokens[1]
    request_target = first_line_tokens[1].split('/')[-1]
    if not request_target:
        request_target = "/"

    return server_url, request_target

def is_cache_expired(cache_key):
    if cache_key in cache:
        cached_time, _, _ = cache[cache_key]
        current_time = time.time()
        return current_time - cached_time > cache_expiration_time
    return True

def update_cache(request, image_header, image):
    server_url, request_target = parse_request(request)
    cache_key = (server_url, request_target)
    cache[cache_key] = (time.time(), image_header, image)

def get_cache_image(request):
    # Parse the request to get the server_url, request_target, and extension
    server_url, request_target = parse_request(request)
    extension = '.' + request_target.split('.')[-1] if '.' in request_target else ""
    
    # Check if the requested extension is supported
    if extension not in image_extensions:
        return False, b""
    
    cache_key = (server_url, request_target)
    
    # Check if the image is in cache and if it's expired
    if cache_key in cache and not is_cache_expired(cache_key):
        cached_time, image_header, image = cache[cache_key]
        response = image_header + b"\r\n\r\n" + image
        return True, response
    
    # Define paths for the image and its header in the cache
    image_path = os.path.join(os.getcwd(), 'cache', server_url, request_target)
    image_header_path = os.path.join(os.getcwd(), 'cache', server_url, f"{request_target.rsplit('.', 1)[0]}.txt")
    
    # Retrieve image from cache or load from disk
    image = load_file(image_path)
    image_header = load_file(image_header_path)
    if image is None or image_header is None:
        return False, b""
    
    # Update cache with new data
    update_cache(request, image_header, image)
    
    response = image_header + b"\r\n\r\n" + image
    return True, response

def save_cache_image(request, response):
    # Parse the request to get the server_url, request_target and extension
    server_url, request_target = parse_request(request)
    extension = '.' + request_target.split('.')[-1] if '.' in request_target else ""

    # Check if the requested extension is supported
    if extension not in image_extensions:
        return False, b""
    
    # Define the folder path based on the server URL
    path = os.path.join(os.getcwd(), 'cache', server_url)
    
    # If the folder does not exist, create that folder
    if not os.path.exists(path):
        os.makedirs(path)

    # Define the file paths within the created folder
    image_path = os.path.join(path, f"{request_target}")
    image_header_path = os.path.join(path, f"{request_target.rsplit('.', 1)[0]}.txt")

    # Save image to cache
    image_header, _, image = response.partition(b"\r\n\r\n")
    with open(image_path, "wb") as image_file, open(image_header_path, "wb") as header_file:
        image_file.write(image)
        header_file.write(image_header)

# -----------------------------  PROXY SERVER  -----------------------------#

def handle_GET(request):
    # If cached, return cached reply
    is_cache, response = get_cache_image(request)
    if is_cache:
        print("\r\nGet cached image successfully\r\n")
        return response

    # Parse the request to get the method, server_url and request_target
    method = request.split('\r\n')[0]
    server_url, request_target = parse_request(request)
    request_target = "/" + request_target

    # Create request to be sent to web server
    response = f"GET {request_target} HTTP/1.1\r\nHost: {server_url}\r\nConnection: close\r\n\r\n"

    # Connect to web server and get reply
    webSerSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    webSerSock.connect((server_url, 80))
    webSerSock.send(response.encode())

    # Receive reply from web server
    data = b""
    while True:
        chunk = webSerSock.recv(BUFFER_SIZE)
        if not chunk:
            break
        data += chunk

    save_cache_image(request, data)
    webSerSock.close()
    return data

def handle_POST(request):
    # If cached, return cached reply
    is_cache, response = get_cache_image(request)
    if is_cache:
        print("\r\nGet cached image successfully\r\n")
        return response

    # Parse the request to get the method, server_url and request_target
    method = request.split('\r\n')[0]
    server_url, request_target = parse_request(request)
    request_target = "/" + request_target

    # Create request to be sent to web server
    response = f"POST {request_target} HTTP/1.1\r\n"

    if request.decode('latin1').find("Connection: ") != -1:
        response += request.decode('latin1').partition("\r\n")[2].partition("Connection: ")[0]
        response += "Connection: close\r\n"
        response += request.decode('latin1').partition("Connection: ")[2].partition("\r\n")[2]
    else:
        temp = request.decode('latin1').partition("\r\n\r\n")
        response += temp[0]
        response += "\r\nConnection: close\r\n\r\n"
        response += temp[2]

    # Connect to web server and get reply
    webSerSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    webSerSock.connect((server_url, 80))
    webSerSock.send(request.encode())

    # Receive reply from web server
    data = b""
    while True:
        chunk = webSerSock.recv(BUFFER_SIZE)
        if not chunk:
            break
        data += chunk

    save_cache_image(request, data)
    webSerSock.close()
    return data

def handle_HEAD(request):
    # If cached, return cached reply
    is_cache, response = get_cache_image(request)
    if is_cache:
        print("\r\nGet cached image successfully\r\n")
        return response

    # Parse the request to get the method, server_url and request_target
    method = request.split('\r\n')[0]
    server_url, request_target = parse_request(request)
    request_target = "/" + request_target

    # Create request to be sent to web server
    response = f"HEAD {request_target} HTTP/1.1\r\nHost: {server_url}\r\nConnection: close\r\n\r\n"

    # Connect to web server and get reply
    webSerSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    webSerSock.connect((server_url, 80))
    webSerSock.send(response.encode())

    # Receive reply from web server
    data = b""
    while True:
        chunk = webSerSock.recv(BUFFER_SIZE)
        if not chunk:
            break
        data += chunk
        if b'\r\n\r\n' in data:
            break

    save_cache_image(request, data)
    webSerSock.close()
    return data

def handle_client(tcpCliSock):
    request = tcpCliSock.recv(BUFFER_SIZE).decode('latin1')
        
    if not request:
        print("Error: Invalid request")
        tcpCliSock.close()
        return
        
    # Parse the request to get the method, URL and protocol
    method, url, protocol = request.split('\r\n')[0].split()
    domain = get_domain_from_url(url)
        
    # Check if the method is allowed
    if method not in ["GET", "POST", "HEAD"]:
        print("\n\nError: Do not support other methods, apart from: GET, POST, HEAD")
        serve_403_response(tcpCliSock)
        return

    print(f"\n\n[+] Accepted connection from {tcpCliSock.getpeername()[0]}:{tcpCliSock.getpeername()[1]}")
    print(f"URL: {url}")
    print(request, end='')
        
    # Check if the URL is in whitelisting
    # if not is_whitelisting(domain, whitelisting):
    #     print("Error: Not in whitelist")
    #     serve_403_response(tcpCliSock)``
    #     return
        
    # Check if the time is in allowed time
    if not is_allowed_time(time_restriction):
        print ("Error: Time restriction")
        serve_403_response(tcpCliSock)
        return 
    
    # Handle request
    if method == 'GET':
        response = handle_GET(request)
    elif method == 'POST':
        response = handle_POST(request)
    else:
        response = handle_HEAD(request)
        
    # Reply to client
    tcpCliSock.sendall(response)
    print(tcpCliSock, "closed")
    tcpCliSock.close()

def main():
    if len(sys.argv) != 3:
        print('Usage : "python ProxyServer.py [server_IP] [server_PORT]" ') 
        print('+ server_IP  : It is the IP Address of Proxy Server')
        print('+ server_PORT: It is the PORT of Proxy Server')
        sys.exit(2)

    # Get the host and port from the arguments
    HOST = sys.argv[1]
    PORT = int(sys.argv[2])

    # Create a server socket, bind it to a port and start listening
    tcpSerSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcpSerSock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcpSerSock.bind((HOST, PORT))
    tcpSerSock.listen(MAX_CONNECTIONS)
    print(f"Proxy server is listening on {HOST}:{PORT}")

    while True: 
        try:
            # Accept a connection from a client
            tcpCliSock, addr = tcpSerSock.accept()

            # Start a new thread to handle the request from the client
            thread.start_new_thread(handle_client, (tcpCliSock, ))

        except KeyboardInterrupt: # Catch the keyboard interrupt exception
            tcpCliSock.close()
            tcpSerSock.close()
            print ("Turning off Proxy Server!")
            break
            
if __name__ == "__main__":
    main()

# Testing Sample: python ProxyServer.py 127.0.0.1 8888