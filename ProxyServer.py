import socket
import os
import _thread as thread
import datetime, time

CACHE_DIRECTORY = "cache"
CONFIG_FILE = "config.conf"

# Generate folder "cache" whether not exist
if not os.path.exists(CACHE_DIRECTORY):
    os.makedirs(CACHE_DIRECTORY)

time_caching_images_file = os.path.join(CACHE_DIRECTORY, 'time_caching_images.txt')
if not os.path.exists(time_caching_images_file):
    with open(time_caching_images_file, 'a+') as f:
        pass

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
def is_whitelisting(domain):
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

def timing_caching_image(image_url):
    flag = False
    with open(time_caching_images_file, 'r') as file:
        lines = file.readlines()

    with open(time_caching_images_file, 'w') as file:
        for line in lines:
            if image_url in line:
                print("Update time caching image successfully!")
                # Update the cached time in the line
                current_time = time.time()
                updated_line = f"{image_url} {current_time}\n"
                file.write(updated_line)
                flag = True
            else:
                file.write(line)

        if flag == False:
            print("Save time caching image successfully!")
            current_time = time.time()
            new_line = f"{image_url} {current_time}\n"
            file.write(new_line)
    
def get_cached_response(image_url):
    # Find domain and path
    domain = image_url.split('/')[0]
    filename = image_url.split('/')[-1]
    
    # Implementation to check cache expiration
    current_time = time.time()
    cached_time = None
    with open(time_caching_images_file, 'r') as file:
        for line in file:
            if image_url in line:
                cached_time = float(line.split(' ')[1])
                break

    if cached_time is not None and current_time - cached_time <= cache_expiration_time:
        image_path = os.path.join(CACHE_DIRECTORY, domain, filename)
        file_extension = filename.split('.')[-1]

        content_type = f"image/{file_extension}"

        try:
            with open(image_path, 'rb') as f:
                image_data = f.read()
            return content_type, image_data
        except FileNotFoundError:
            print("Image file not found:", image_path)
            return None
        except Exception as e:
            print("Error reading image file:", e)
            return None
    else:
        return None

def save_cache_image(request, response):
    parsed_request = parse_request(request)
    total_url = parsed_request["total_url"]

    domain = total_url.split('/')[0]
    path = '/' + '/'.join(total_url.split('/')[1:])

    headers, image_data = response.split(b'\r\n\r\n', 1)

    if b"Content-Type: image/" in headers:
        extension = '.' + path.split('.')[-1] if '.' in path else ""

    
        # Create cache folder if it doesn't exist
        image_folder = os.path.join(CACHE_DIRECTORY, domain)
        if not os.path.exists(image_folder):
            os.makedirs(image_folder)
        
        image_path = os.path.join(image_folder, f"{os.path.basename(path).rsplit('.', 1)[0]}{extension}")
    
        # print(f"Headers: {headers}")
        # print(f"Image data: {image_data}")

        # Save the binary image data
        with open(image_path, "wb") as image_file:
            image_file.write(image_data)
            print("Save cached image successfully!")

        # Save caching time to "time_caching_images_file"
        timing_caching_image(total_url)

def handle_request(request):
    # Parse the request to get the method and total_url
    parsed_request = parse_request(request)
    total_url = parsed_request["total_url"]
    method = parsed_request["method"]

    # Find domain and path
    domain = total_url.split('/')[0]
    path = '/' + '/'.join(total_url.split('/')[1:])

    cached_response = get_cached_response(total_url)
    if cached_response is not None:
        content_type, image_data = cached_response
    else:
        content_type, image_data = None, None

    if content_type is not None and image_data is not None:
        print("Get cached image successfully!")
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
        request_to_send = f"HEAD {path} HTTP/1.0\r\nHost: {domain}\r\nConnection: close\r\n\r\n"

    # Connect to web server and get reply
    webSerSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    webSerSock.connect((domain, 80))
    webSerSock.send(request_to_send.encode("ISO-8859-1"))

    # Receive response from web server
    response = b""
    while True:
        chunk = webSerSock.recv(buffer_size)
        if not chunk:
            break
        response += chunk
    
    response_str = response.decode("ISO-8859-1")

    # Handle "Transfer-Encoding: chunked" if exist in response headers
    if "Transfer-Encoding: chunked" in response_str:
        # Split the response into chunks
        chunks = response_str.split("\r\n")
        
        # Process each chunk separately
        decoded_chunks = []
        for chunk in chunks:
            if len(chunk) > 0 and chunk[0] != '\r':
                decoded_chunks.append(chunk)
                
        # Reconstruct the response from the decoded chunks
        response_str = "\r\n".join(decoded_chunks)
    
    # Handle "Content-Length" if exist in response headers
    elif "Content-Length:" in response_str:
        # Find the value of the Content-Length header
        content_length_index = response_str.find("Content-Length:")
        content_length_value_index = content_length_index + len("Content-Length:")
        content_length_end_index = response_str.find("\r", content_length_value_index)
        
        content_length_str = response_str[content_length_value_index:content_length_end_index].strip()
        
        # Convert the Content-Length value to an integer
        content_length = int(content_length_str)
        
        # Truncate the response to the specified Content-Length
        body_start_index = response_str.find("\r\n\r\n") + len("\r\n\r\n")
        
        if len(response_str) >= body_start_index + content_length:
            response_str = response_str[:body_start_index + content_length]
    
    # Check if the response contains image data
    if "Content-Type: image/" in response.decode("ISO-8859-1"):
        save_cache_image(request, response)
    
    webSerSock.close()
    
    return response_str.encode("ISO-8859-1")

def handle_client(tcpCliSock):
    request = tcpCliSock.recv(buffer_size).decode("ISO-8859-1")
        
    if not request:
        print("Error: Invalid request")
        tcpCliSock.close()
        return
        
    # Parse the request to get the method and total_url
    parsed_request = parse_request(request)
    method = parsed_request["method"]
    total_url = parsed_request["total_url"]
    domain = parsed_request["domain"]

    # Check if the method is allowed
    if method not in ["GET", "POST", "HEAD"]:
        print("\n\nError: Do not support other methods, apart from: GET, POST, HEAD")
        serve_403_response(tcpCliSock)
        tcpCliSock.close()
        return

    print(f"\n\n[+] Accepted connection from {tcpCliSock.getpeername()[0]}:{tcpCliSock.getpeername()[1]}")
    print(f"URL: {total_url}")
    print(request, end='')
        
    # Check if the URL is in whitelisting
    if enable_whitelisting == True:
        if not is_whitelisting(domain):
            print("Error: Not in whitelist")
            serve_403_response(tcpCliSock)
            tcpCliSock.close()
            return
        
    # Check if the time is in allowed time
    if enable_time_restriction == True: 
        if not is_allowed_time(time_restriction):
            print ("Error: Time restriction")
            serve_403_response(tcpCliSock)
            tcpCliSock.close()
            return 
    
    # Handle request
    if method in ["GET", "POST", "HEAD"]:
        response = handle_request(request)

    # Reply to client
    tcpCliSock.sendall(response)
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