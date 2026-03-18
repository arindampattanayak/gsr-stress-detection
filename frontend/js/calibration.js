

const ctx = document.getElementById('chart').getContext('2d');

const chart = new Chart(ctx,{
type:'line',

data:{
labels:[],
datasets:[{
label:'GSR Signal',
data:[],
borderWidth:2,
fill:false,
tension:0.2
}]
},

options:{
animation:false,
scales:{
x:{display:false}
}
}

});


// Update Graph
function updateChart()
{
fetch("/get_data")
.then(response=>response.json())
.then(data=>{

chart.data.labels = data.map((_,i)=>i);
chart.data.datasets[0].data = data;

chart.update();

});
}


// Update Features
function updateFeatures()
{
fetch("/get_features")
.then(response=>response.json())
.then(d=>{

if(Object.keys(d).length===0) return;

document.getElementById("mean").innerText = d.mean.toFixed(4);
document.getElementById("std").innerText = d.std.toFixed(4);
document.getElementById("slope").innerText = d.slope.toFixed(6);
document.getElementById("peaks").innerText = d.peak_count;
document.getElementById("rise").innerText = d.rise_time.toFixed(2);
document.getElementById("scr").innerText = d.scr.toFixed(4);

});
}


// Set Stress Label
function setLabel(label)
{

fetch("/set_label",{

method:"POST",

headers:{
"Content-Type":"application/json"
},

body:JSON.stringify({label:label})

});

}


// Download Dataset
function downloadCSV()
{

window.open("/gsr_dataset.csv");

}


// Update continuously
setInterval(updateChart,500);
setInterval(updateFeatures,500);