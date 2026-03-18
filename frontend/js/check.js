
let values = []
let interval = null
let timerInterval = null
let seconds = 0

function startLive(){

document.getElementById("status").innerText="Recording started"

values = []
seconds = 0

timerInterval = setInterval(()=>{
seconds++
document.getElementById("timer").innerText="Timer: "+seconds+" sec"

if(seconds>=40){
stopLive()
}
},1000)

interval = setInterval(()=>{

fetch("/get_data")
.then(r=>r.json())
.then(data=>{

if(data.length>0){
values.push(data[data.length-1])
}

})

},200)

}

function stopLive(){

if(interval){
clearInterval(interval)
clearInterval(timerInterval)

document.getElementById("status").innerText="Recording stopped"

document.getElementById("live_data").value =
JSON.stringify(values)

}

}