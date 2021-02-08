import subprocess
import re

pattern = re.compile("temp=(\\d*.\\d*).*")

execRes = subprocess.run(['vcgencmd', 'measure_temp'], capture_output=True)

if execRes.returncode == 0:
    print('measure succeeded')
    print('Stdout: ', execRes.stdout.decode('utf-8'))
    print('Stderr: ', execRes.stderr.decode('utf-8'))
    print('Temperature: '+pattern.match(execRes.stdout.decode('utf-8')).group(1))

else:
    print('measure failed. Return code: ', execRes.returncode)
    print('Stdout: ', execRes.stdout.decode('utf-8'))
    print('Stderr: ', execRes.stderr.decode('utf-8'))

exit()


