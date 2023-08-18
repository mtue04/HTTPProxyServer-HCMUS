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

# Generate folder "cache" whether not exist
if not os.path.exists(CACHE_DIRECTORY):
    os.makedirs(CACHE_DIRECTORY)

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
    max_connection = int(config.get('max_connection', 0))
    buffer_size = int(config.get('buffer_size', 0))
    enable_whitelisting = config.get('enable_whitelisting', '').lower() == 'true'
    whitelisting = set(map(str.strip, config.get('whitelisting', '').split(',')))
    enable_time_restriction = config.get('enable_time_restriction', '').lower() == 'true'
    time_restriction = config.get('time_restriction', '')

    return {
        'cache_time': cache_time,
        'max_connection': max_connection,
        'buffer_size': buffer_size,
        'enable_whitelisting': enable_whitelisting,
        'whitelisting': whitelisting,
        'enable_time_restriction': enable_time_restriction,
        'time_restriction': time_restriction
    }

config_values = read_config(CONFIG_FILE)
cache_expiration_time = config_values['cache_time']
max_connection = config_values['max_connection']
buffer_size = config_values['buffer_size']
enable_whitelisting = config_values['enable_whitelisting']
whitelisting = list(config_values['whitelisting'])
enable_time_restriction = config_values['enable_time_restriction']
time_restriction = config_values['time_restriction']

# Check whether time is in allowed time
def is_allowed_time(time_restriction):
    now = datetime.datetime.now()
    current_time = now.time()
    
    if "-" in time_restriction:
        start_time_str, end_time_str = time_restriction.split("-")
        start_time = datetime.datetime.strptime(start_time_str, "%H:%M").time()
        end_time = datetime.datetime.strptime(end_time_str, "%H:%M").time()
        
        if start_time <= current_time <= end_time:
            return True
    else:
        return False

# Check whether website is in whitelisting
def is_whitelisting(url):
    # Delete 'http://'
    if url.startswith("http://"):
        url = url[len("http://"):]

    # Find index of the first '/' after domain
    slash_index = url.find("/")
    if slash_index != -1:
        domain = url[:slash_index]
    else:
        domain = url

    for allowed_domain in whitelisting:
        if domain in allowed_domain:
            return True
    return False

# Response Error 403
def serve_403_response(tcpCliSock):
    header_content = b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/html\r\n\r\n"

    # PATH to Error 403 HTML file
    error403_path = r"index.html"

    with open(error403_path, "rb") as error_file:
        body_content = error_file.read()

    tcpCliSock.send(header_content + body_content)
    return

# Parse the request into dictionary of request
def parse_request(client_data):
    if isinstance(client_data, bytes):
        client_data = client_data.decode("ISO-8859-1")
        
    # Split client_data into lines and remove empty lines
    lines = client_data.splitlines()
    while lines[len(lines)-1] == '':
        lines.remove('')

    # Parse the first line of the request
    first_line_tokens = lines[0].split()
    url = first_line_tokens[1]

    # Parse the protocol and URL from the request URL
    url_pos = url.find("://")
    if url_pos != -1:
        protocol = url[:url_pos]
        url = url[(url_pos+3):]
    else:
        protocol = "http"

    # Parse the port and path from the request URL
    port_pos = url.find(":")
    path_pos = url.find("/")
    if path_pos == -1:
        path_pos = len(url)

    if port_pos == -1 or path_pos < port_pos:
        server_port = 80
        domain = url[:path_pos]
    else:
        server_port = int(url[port_pos + 1:path_pos])
        domain = url[:port_pos]

    # Modify request to be sent to the server
    first_line_tokens[1] = url[path_pos:]
    lines[0] = ' '.join(first_line_tokens)
    client_data = "\r\n".join(lines) + '\r\n\r\n'

    return {
        "server_port": server_port,
        "domain": domain,
        "total_url": url,
        "client_data": client_data,
        "protocol": protocol,
        "method": first_line_tokens[0],
    }

#-------------------------  HANDLE CACHE IMAGE  -------------------------#
    
def load_image(image_path):
    with open(image_path, "rb") as image_file:
        image_data = image_file.read()
    return image_data

def is_cache_expired(cache_key, cache_time):
    if cache_key in cache:
        cached_time, _, _ = cache[cache_key]
        current_time = time.time()
        return current_time - cached_time > cache_time
    return True

def get_cached_response(url, webserver, filename):
    # Your implementation to check cache expiration here
    cache_expired = is_cache_expired((webserver, filename), cache_expiration_time)
    
    if not cache_expired:
        image_path = os.path.join(CACHE_DIRECTORY, webserver, filename)
        file_extension = filename.split('.')[-1]
        content_type = f"Content-Type: image/{file_extension}"
        with open(image_path, 'rb') as f:
            image_data = f.read()
        return content_type, image_data

    return None, None

def save_cache_image(request, response, cache_time):
    parsed_request = parse_request(request)
    total_url = parsed_request["total_url"]

    domain = total_url.split('/')[0]
    path = '/' + '/'.join(total_url.split('/')[1:])

    extension = '.' + path.split('.')[-1] if '.' in path else ""

    if extension not in image_extensions:
        return False, b""
    
    # Create cache folder if it doesn't exist
    image_folder = os.path.join(CACHE_DIRECTORY, domain)
    if not os.path.exists(image_folder):
        os.makedirs(image_folder)
    
    # Create image subfolder if it doesn't exist
    if not os.path.exists(image_folder):
        os.makedirs(image_folder)
    
    image_path = os.path.join(image_folder, f"{os.path.basename(path).rsplit('.', 1)[0]}.{extension}")
    headers, image_data = response.split(b'\r\n\r\n', 1)
    # print(f"Headers: {headers}")
    # print(f"Image data: {image_data}")

    # Save the binary image data
    with open(image_path, "wb") as image_file:
        image_file.write(image_data)

    # Save caching time to a text file
    cache_time_file = os.path.join(image_folder, f"{os.path.basename(path).rsplit('.', 1)[0]}.txt")
    with open(cache_time_file, "w") as time_file:
        time_file.write(str(time.time()))

# def store_image_in_cache(url, image_data, webserver):
#     web_server_folder = os.path.join(CACHE_DIRECTORY, webserver)
#     if not os.path.exists(web_server_folder):
#         os.makedirs(web_server_folder)

#     filename = os.path.basename(url)
#     image_path = os.path.join(web_server_folder, filename)
#     with open(image_path, 'wb') as f:
#         f.write(image_data)

#     cache_time_file = os.path.join(web_server_folder, f"{filename.rsplit('.', 1)[0]}.txt")
#     with open(cache_time_file, "w") as time_file:
#         time_file.write(str(time.time()))

# -----------------------------  PROXY SERVER  -----------------------------#

def handle_request(request):
    # Parse the request to get the method and total_url
    parsed_request = parse_request(request)
    total_url = parsed_request["total_url"]
    method = parsed_request["method"]

    # Find domain and path
    domain = total_url.split('/')[0]
    path = '/' + '/'.join(total_url.split('/')[1:])

    content_type, image_data = get_cached_response(total_url, domain, path)
    
    if content_type and image_data:
        return image_data

    # Build the appropriate request for the web server
    if method == "GET":
        request_to_send = f"GET {path} HTTP/1.0\r\nHost: {domain}\r\nConnection: close\r\n\r\n"
        
    if method == "POST":
        request_to_send = f"POST {path} HTTP/1.0\r\n"
        if "Connection: " in request:
            request_to_send += request.partition("\r\n")[2].partition("Connection: ")[0]
            request_to_send += "Connection: close\r\n"
            request_to_send += request.partition("Connection: ")[2].partition("\r\n")[2]
        else:
            request_to_send += request.partition("\r\n\r\n")[0] 
            request_to_send += "\r\nConnection: close\r\n\r\n" 
            request_to_send += request.partition("\r\n\r\n")[2]

    if method == "HEAD":
        request_to_send = f"HEAD {path} HTTP/1.0\r\nHost: {domain}\r\nAccept: text/html\r\nConnection: close\r\n\r\n"

    # Connect to web server and get reply
    webSerSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    webSerSock.connect((domain, 80))
    webSerSock.send(request_to_send.encode("ISO-8859-1"))

    # Receive reply from web server
    data = b""
    while True:
        chunk = webSerSock.recv(BUFFER_SIZE)
        if not chunk:
            break
        data += chunk

    # Check if the response contains image data
    if "Content-Type: image/" in data.decode("ISO-8859-1"):
        save_cache_image(request, data, cache_expiration_time)
        # store_image_in_cache(total_url, data, domain)

    webSerSock.close()
    return data

def handle_client(tcpCliSock):
    request = tcpCliSock.recv(BUFFER_SIZE).decode("ISO-8859-1")
        
    if not request:
        print("Error: Invalid request")
        tcpCliSock.close()
        return
        
    # Parse the request to get the method and total_url
    parsed_request = parse_request(request)
    method = parsed_request["method"]
    total_url = parsed_request["total_url"]
        
    # Check if the method is allowed
    if method not in ["GET", "POST", "HEAD"]:
        print("\n\nError: Do not support other methods, apart from: GET, POST, HEAD")
        serve_403_response(tcpCliSock)
        return

    print(f"\n\n[+] Accepted connection from {tcpCliSock.getpeername()[0]}:{tcpCliSock.getpeername()[1]}")
    print(f"URL: {total_url}")
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
    if method in ["GET", "POST", "HEAD"]:
        response = handle_request(request)

    # Reply to client
    tcpCliSock.sendall(response)
    print(tcpCliSock, "closed")
    tcpCliSock.close()

def main():
    # if len(sys.argv) != 3:
    #     print('Usage : "python ProxyServer.py [server_IP] [server_PORT]" ') 
    #     print('+ server_IP  : It is the IP Address of Proxy Server')
    #     print('+ server_PORT: It is the PORT of Proxy Server')
    #     sys.exit(2)

    # # Get the host and port from the arguments
    # HOST = sys.argv[1]
    # PORT = int(sys.argv[2])

    # For testing
    HOST = "127.0.0.1"
    PORT = 8888
    # # # # 

    # Create a server socket, bind it to a port and start listening
    tcpSerSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcpSerSock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcpSerSock.bind((HOST, PORT))
    tcpSerSock.listen(max_connection)
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