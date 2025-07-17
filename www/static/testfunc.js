function toggle_visibility(onid, offid, onlinkid, offlinkid) {
  var one = document.getElementById(onid);
  var offe = document.getElementById(offid);
  var linkone = document.getElementById(onlinkid);
  var linkoffe = document.getElementById(offlinkid);
  one.style.display = 'block';
  offe.style.display = 'none';
  linkone.className = 'thispage';
  linkoffe.className = '';
}

function show_conda() {
  var one = document.getElementById('conda_install');
  if (one.style.display == 'block') {
    one.style.display = 'none';
  } else {
    one.style.display = 'block';
  }
}

function toggle_detail(num) {
  var detail = document.getElementById("detail" + num);
  var dettog = document.getElementById("dettog" + num);
  if (detail.style.display == 'block') {
    detail.style.display = 'none';
    dettog.innerHTML = '[+]';
  } else {
    detail.style.display = 'block';
    dettog.innerHTML = '[-]';
  }
}

function toggle_all_detail() {
  var dettog = document.getElementById("dettog");
  var dettogs = document.getElementsByClassName("dettog");
  var details = document.getElementsByClassName("detail");
  
  var disp;
  var newtog;
  if (dettog.innerHTML == '[+]') {
    disp = 'block';
    newtog = '[-]'
  } else {
    disp = 'none';
    newtog = '[+]'
  }
  for (var i = 0; i < details.length; ++i) {
    details[i].style.display = disp;
  }
  for (var i = 0; i < dettogs.length; ++i) {
    dettogs[i].innerHTML = newtog;
  }
}

/* e-mail obfuscation adapted from code by Jason Johnston:
   http://lojjic.net/blog/20030828-142754.rdf.html
*/
function linkEmail() {
  if(!document.getElementsByTagName) return;
  var allElts = document.getElementsByTagName("*");
  if(allElts.length == 0 && document.all) 
    allElts = document.all; //hack for IE5
  for(var i=0; i<allElts.length; i++) {
    var elt = allElts[i];
    var className = elt.className || elt.getAttribute("class") 
      || elt.getAttribute("className");
    if(className && className.match(/\be-mail\b/)
        && elt.firstChild.nodeType == 3) {
      var alls = elt.firstChild.nodeValue;
      fs= alls.split("|")
      addr = fs[0].replace(/\ at\ /i, "@")
        .replace(/\ (dot|period)\ /gi, ".");
      var lnk = document.createElement("a");
      lnk.setAttribute("href","mailto:"+addr);
      lnk.appendChild(document.createTextNode(fs[1]));
      elt.replaceChild(lnk, elt.firstChild);
    }
  }
}
