#!/bin/sh
echo "Starting CTFsub process!"

if test -f "stop.sh"; then
    echo "The program is running!"
    echo "Close first it running ./stop.sh"
    exit 1
fi
echo "run stop.sh for kill the process"
echo "the file 'stop.sh' will be removed after his execution"
nohup /usr/bin/python3 start.py >/dev/null 2>&1 < /dev/null &
echo "#!/bin/sh" > stop.sh
echo "echo \"Killing CTFsub process!\"; echo \"run ./run.sh for restart the process\";kill -9 $!;rm stop.sh" >> stop.sh
chmod +x stop.sh
