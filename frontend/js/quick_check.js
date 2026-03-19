let dataBuffer = [];
let timer = 0;
let interval = null;
let isRecording = false;

function startLive() {

    dataBuffer = [];
    timer = 0;
    isRecording = true;

    document.getElementById("status").innerText = "Recording started...";

    interval = setInterval(() => {

        fetch("/get_data")
        .then(res => res.json())
        .then(data => {

            if (data.length > 0) {
                dataBuffer.push(data[data.length - 1]);
            }

        });

        timer++;
        document.getElementById("timer").innerText = timer;

        // AUTO STOP at 40 sec
        if (timer >= 40) {
            stopLive();
        }

    }, 1000);
}

function stopLive() {

    clearInterval(interval);
    isRecording = false;

    document.getElementById("status").innerText = "Recording stopped";

    document.getElementById("live_data").value = JSON.stringify(dataBuffer);
}