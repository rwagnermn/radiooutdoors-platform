(function(){
"use strict";
const trigger=document.querySelector("[data-location-help-open]");
const dialog=document.querySelector("[data-location-help-dialog]");
if(!trigger||!dialog)return;
const focusable=()=>Array.from(dialog.querySelectorAll('button,[href],[tabindex]:not([tabindex="-1"])'));
function close(){dialog.hidden=true;document.body.classList.remove("location-help-open");trigger.focus();}
function open(){dialog.hidden=false;document.body.classList.add("location-help-open");dialog.querySelector("[data-location-help-close]").focus();}
trigger.addEventListener("click",open);
dialog.querySelectorAll("[data-location-help-close]").forEach(button=>button.addEventListener("click",close));
dialog.addEventListener("click",event=>{if(event.target===dialog)close();});
dialog.addEventListener("keydown",event=>{if(event.key==="Escape"){event.preventDefault();close();return;}if(event.key!=="Tab")return;const items=focusable();const first=items[0],last=items[items.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}});
})();
