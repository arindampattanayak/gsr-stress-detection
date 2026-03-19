let relaxedData=[]
let stressData=[]

let mode=""
let timer=0
let interval=null

// RECORDING TIME (seconds)
const RECORD_TIME = 180

const autoCtx=document.getElementById("recordChart").getContext("2d")

const recordChart=new Chart(autoCtx,{
type:"line",
data:{
labels:[],
datasets:[{
label:"GSR Signal",
data:[],
borderColor:"red",
fill:false
}]
}
})

function startRelaxed(){

mode="relaxed"
timer=0
relaxedData=[]

// clear chart
recordChart.data.labels=[]
recordChart.data.datasets[0].data=[]
recordChart.update()

fetch("/set_label",{
method:"POST",
headers:{"Content-Type":"application/json"},
body:JSON.stringify({label:0})
})

startRecording()

}

function startStress(){

mode="stress"
timer=0
stressData=[]

// clear chart
recordChart.data.labels=[]
recordChart.data.datasets[0].data=[]
recordChart.update()

fetch("/set_label",{
method:"POST",
headers:{"Content-Type":"application/json"},
body:JSON.stringify({label:1})
})

startRecording()

}

function startRecording(){

// prevent multiple intervals
if(interval){
clearInterval(interval)
}

interval=setInterval(()=>{

fetch("/get_data")
.then(res=>res.json())
.then(data=>{

if(data.length===0) return

let value=data[data.length-1]

// update graph
recordChart.data.labels.push(timer)
recordChart.data.datasets[0].data.push(value)

recordChart.update()

// store data
if(mode==="relaxed") relaxedData.push(value)
if(mode==="stress") stressData.push(value)

timer++

document.getElementById("timer").innerText=timer

// stop recording after RECORD_TIME
if(timer>=RECORD_TIME){

clearInterval(interval)

if(mode==="relaxed"){
alert("Relaxed Recording Complete")
}

if(mode==="stress"){
alert("Stress Recording Complete")
}

}

})

},1000)

}

function saveCalibration(){

if(relaxedData.length===0 || stressData.length===0){
alert("Please record both Relaxed and Stress data first")
return
}

fetch("/save_auto_calibration",{
method:"POST",
headers:{"Content-Type":"application/json"},
body:JSON.stringify({
relaxed:relaxedData,
stress:stressData
})
})
.then(res=>res.json())
.then(data=>{

console.log("Relaxed Features:", data.relaxed_features)
console.log("Stress Reference:", data.stress_reference)
console.log("Delta Thresholds:", data.delta_thresholds)

alert("Calibration Stored Successfully")

})
}