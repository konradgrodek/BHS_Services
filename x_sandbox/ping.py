import subprocess

execRes = subprocess.run(['ping', '-c 1', 'www.google.com'], capture_output=True)

if execRes.returncode == 0:
    print('ping execution succeeded')
    print('Stdout: ', execRes.stdout.decode('utf-8'))
    print('Stderr: ', execRes.stderr.decode('utf-8'))

else:
    print('ping failed. Return code: ', execRes.returncode)
    print('Stdout: ', execRes.stdout.decode('utf-8'))
    print('Stderr: ', execRes.stderr.decode('utf-8'))

exit()

"""
success:

PING www.google.com (172.217.16.36) 56(84) bytes of data.
64 bytes from waw02s14-in-f4.1e100.net (172.217.16.36): icmp_seq=1 ttl=56 time=13.2 ms

--- www.google.com ping statistics ---
1 packets transmitted, 1 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 13.241/13.241/13.241/0.000 ms

failure:

ping failed. Return code:  2
Stdout:  
Stderr:  ping: www.gosfdsdjogle.com: Name or service not known

failure2:

ping failed. Return code:  2
Stdout:  
Stderr:  ping: www.google.com: Temporary failure in name resolution


Process finished with exit code 0

failure 3

ping failed. Return code:  2
Stdout:  
Stderr:  ping: www.google.com: Temporary failure in name resolution




"""




