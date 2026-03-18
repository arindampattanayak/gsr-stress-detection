

let phase = 0;
let cycles = 0;
let maxCycles = 12;

let beforeStress = 0;
let afterStress = 0;

let countdownInterval;


/* Chart Setup */

const ctx = document.getElementById("stressChart").getContext("2d");

const chart = new Chart(ctx, {
type: "line",
data: {
labels: [],
datasets: [{
label: "Stress Signal",
data: [],
borderColor: "#3b82f6",
borderWidth: 2,
fill: false,
tension: 0.3
}]
},
options: {
responsive: true,
animation: false
}
});


/* Live GSR Graph */

function updateChart(){

fetch("/get_data")
.then(r => r.json())
.then(data => {

chart.data.labels = data.map((_,i)=>i);
chart.data.datasets[0].data = data;
chart.update();

});

}


/* LIVE STRESS COLOR FEEDBACK */

function updateStressColor(){

fetch("/get_features")
.then(r=>r.json())
.then(d=>{

if(Object.keys(d).length === 0) return;

let scr = d.scr;

const circle = document.getElementById("breathingCircle");

/* COLOR LOGIC */

if(scr > 0.7){
circle.style.backgroundColor = "#ef4444"; // RED
}
else if(scr > 0.5){
circle.style.backgroundColor = "#f59e0b"; // ORANGE
}
else{
circle.style.backgroundColor = "#22c55e"; // GREEN
}

});

}


setInterval(updateChart,500);
setInterval(updateStressColor,1000);



/* Start Breathing */

function startBreathing(){

cycles = 0;
phase = 0;

fetch("/get_features")
.then(r=>r.json())
.then(d=>{
beforeStress = d.scr || 0;
});

breathingCycle();

}



/* Countdown */

function startCountdown(seconds){

let counter = seconds;

document.getElementById("countdown").innerText = counter;

clearInterval(countdownInterval);

countdownInterval = setInterval(()=>{

counter--;
document.getElementById("countdown").innerText = counter;

if(counter <= 0){
clearInterval(countdownInterval);
}

},1000);

}



/* Breathing Logic */

function breathingCycle(){

const circle = document.getElementById("breathingCircle");
const status = document.getElementById("breathStatus");
const progress = document.getElementById("cycleProgress");

progress.innerText = (cycles + 1) + "/" + maxCycles;

if(cycles >= maxCycles){
finishExercise();
return;
}


/* Inhale */

if(phase === 0){

status.innerText = "Inhale";
circle.style.transform = "scale(1.4)";
circle.innerText = "Inhale";

startCountdown(4);

setTimeout(()=>{
phase = 1;
breathingCycle();
},4000);

}


/* Hold */

else if(phase === 1){

status.innerText = "Hold";
circle.innerText = "Hold";

startCountdown(4);

setTimeout(()=>{
phase = 2;
breathingCycle();
},4000);

}


/* Exhale */

else{

status.innerText = "Exhale";
circle.style.transform = "scale(1)";
circle.innerText = "Exhale";

startCountdown(6);

setTimeout(()=>{
phase = 0;
cycles++;
breathingCycle();
},6000);

}

}



/* Finish */

function finishExercise(){

fetch("/get_features")
.then(r=>r.json())
.then(d=>{

afterStress = d.scr || 0;

let reduction = ((beforeStress - afterStress)/beforeStress)*100;

if(reduction < 0) reduction = 0;

document.getElementById("resultBox").classList.remove("hidden");

document.getElementById("relaxResult").innerText =
"Stress reduced by " + reduction.toFixed(1) + "%";

});

}