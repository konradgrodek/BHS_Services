import subprocess

execRes = subprocess.run(['hostname'], capture_output=True)

if execRes.returncode == 0:
    print('hostname execution succeeded')
    print('Stdout: ', execRes.stdout.decode('utf-8'))
    print('Stderr: ', execRes.stderr.decode('utf-8'))

else:
    print('hostname failed. Return code: ', execRes.returncode)
    print('Stdout: ', execRes.stdout.decode('utf-8'))
    print('Stderr: ', execRes.stderr.decode('utf-8'))

exit()
