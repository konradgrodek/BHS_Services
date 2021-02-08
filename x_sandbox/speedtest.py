import subprocess
import json

execRes = subprocess.run(['speedtest', '--format=json'], capture_output=True)

if execRes.returncode == 0:
    print('Speedtest execution succeeded')

    res = json.loads(execRes.stdout, encoding='utf-8')
    jitterMicroSecs = int(1000*float(res['ping']['jitter']))
    pingMicroSecs = int(1000*float(res['ping']['latency']))
    downloadKbps = int(int(res['download']['bandwidth'])*8/1000)
    uploadKbps = int(int(res['upload']['bandwidth'])*8/1000)
    externalIP = res['interface']['externalIp']

    print(f"Result: "
          f"ping-jitter: {jitterMicroSecs} microsecs, "
          f"ping-latency {pingMicroSecs} microsecs, "
          f"download: {downloadKbps} Kbps, "
          f"upload {uploadKbps} Kbps, "
          f"external-ip: {externalIP}")

else:
    print('Speedtest failed. Return code: ', execRes.returncode)
    print('Stdout: ', execRes.stdout.decode('utf-8'))
    print('Stderr: ', execRes.stderr.decode('utf-8'))

exit()


"""
failure:

Speedtest failed. Return code:  2
Stdout:  
Stderr:  [2020-03-22 14:36:55.564] [error] Trying to get interface information on non-initialized socket.
[2020-03-22 14:37:01.083] [error] Configuration - Couldn't resolve host name (HostNotFoundException)
[2020-03-22 14:37:01.083] [error] Configuration - Cannot retrieve configuration document (0)
[2020-03-22 14:37:01.083] [error] ConfigurationError - Could not retrieve or read configuration (Configuration)
[2020-03-22 14:37:01.084] [error] ConfigurationError - Could not retrieve or read configuration (Configuration)
{"type":"log","timestamp":"2020-03-22T13:37:01Z","message":"Configuration - Could not retrieve or read configuration (ConfigurationError)","level":"error"}

Speedtest failed. Return code:  2
Stdout:  
Stderr:  [2020-03-22 14:40:24.426] [error] Trying to get interface information on non-initialized socket.
[2020-03-22 14:40:29.946] [error] Configuration - Couldn't resolve host name (HostNotFoundException)
[2020-03-22 14:40:29.946] [error] Configuration - Cannot retrieve configuration document (0)
[2020-03-22 14:40:29.946] [error] ConfigurationError - Could not retrieve or read configuration (Configuration)
[2020-03-22 14:40:29.946] [error] ConfigurationError - Could not retrieve or read configuration (Configuration)
{"type":"log","timestamp":"2020-03-22T13:40:29Z","message":"Configuration - Could not retrieve or read configuration (ConfigurationError)","level":"error"}


"""
