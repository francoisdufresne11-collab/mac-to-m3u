from flask import Flask, request, send_file, Response
import requests, os, json, threading, time
from datetime import datetime

app = Flask(__name__)
OUTPUT_DIR = "/tmp/music"
SAVE_DIR   = "/tmp/data"
SAVE_FILE  = os.path.join(SAVE_DIR, "connexions.json")
LOG_FILE   = os.path.join(SAVE_DIR, "historique_connexions.txt")
last_file  = {"path": None}
G = {"pct":0,"msg":"","done":False,"error":"","channels":0,"categories":0,"size_kb":0,"filepath":"","running":False}
S = {"tok":None,"url":None,"portal":None,"mac":None}
PATHS = ["/server/load.php","/stalker_portal/server/load.php","/stalker_portal/c/server/load.php","/c/server/load.php"]

def log_connexion(portal, mac, succes=True):
    os.makedirs(SAVE_DIR, exist_ok=True)
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    statut = "SUCCES" if succes else "ECHEC"
    ligne = "[%s] %s | URL: %s | MAC: %s\n" % (now, statut, portal, mac)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(ligne)
    except: pass

def upd(pct, msg):
    G["pct"]=pct; G["msg"]=msg
    print("[%d%%] %s"%(pct,msg))

def mh(mac):
    return {
        "User-Agent":"Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 4 rev: 1812 Safari/533.3",
        "Accept":"*/*","X-User-Agent":"Model: MAG250; Link: WiFi",
        "Cookie":"mac="+mac+"; stb_lang=en; timezone=Europe/Paris",
        "Referer":"http://localhost/stalker_portal/c/"
    }

def new_tok(portal, mac):
    base = portal.strip().rstrip("/")
    for s in ["/stalker_portal/c","/stalker_portal","/c"]:
        if base.endswith(s): base=base[:-len(s)]
    for path in PATHS:
        url=base+path
        try:
            r=requests.get(url,headers=mh(mac),params={"type":"stb","action":"handshake","token":"","prehash":"0","JsHttpRequest":"1-xml"},timeout=10)
            if r.status_code==200:
                t=r.json().get("js",{}).get("token","")
                if t:
                    S["tok"]=t;S["url"]=url;S["portal"]=portal;S["mac"]=mac
                    return t,url
        except: pass
    return None,None

def do_prof(url,mac,tok):
    h=mh(mac);h["Authorization"]="Bearer "+tok
    try: requests.get(url,headers=h,params={"type":"stb","action":"get_profile","hd":"1","num_banks":"2","sn":"0000000000000","stb_type":"MAG250","image_version":"218","video_out":"hdmi","device_id":"0000000000000","device_id2":"0000000000000","signature":"","auth_second_step":"1","hw_version":"1.7-BD-00","not_valid_token":"0","client_type":"STB","hw_arch":"mipsel","JsHttpRequest":"1-xml"},timeout=10)
    except: pass

def get_cats(url,mac,tok):
    h=mh(mac);h["Authorization"]="Bearer "+tok
    for action in ["get_genres","get_categories","get_itv_genres"]:
        try:
            r=requests.get(url,headers=h,params={"type":"itv","action":action,"JsHttpRequest":"1-xml"},timeout=15)
            js=r.json().get("js",[])
            if isinstance(js,list) and len(js)>0: return js
            if isinstance(js,dict):
                d=js.get("data",js.get("genres",[]))
                if d: return d
        except: pass
    return []

def req_page(portal,mac,tok,url,genre_id,pg):
    for attempt in range(4):
        try:
            h=mh(mac);h["Authorization"]="Bearer "+tok
            r=requests.get(url,headers=h,params={"type":"itv","action":"get_ordered_list","genre":str(genre_id),"force_ch_link_check":"0","fav":"0","sortby":"number","hd":"0","p":str(pg),"JsHttpRequest":"1-xml"},timeout=20)
            if r.status_code!=200 or not r.text or len(r.text.strip())<10:
                time.sleep(1);tok2,url2=new_tok(portal,mac)
                if tok2: tok=tok2;url=url2
                do_prof(url,mac,tok);time.sleep(1);continue
            try: d=r.json(); return d,tok,url
            except:
                time.sleep(1);tok2,url2=new_tok(portal,mac)
                if tok2: tok=tok2;url=url2
                do_prof(url,mac,tok);time.sleep(1);continue
        except requests.exceptions.Timeout: time.sleep(2)
        except Exception as e: print("Err %d: %s"%(attempt+1,str(e)));time.sleep(1)
    return {},tok,url

def get_all_pages(portal,mac,tok,url,genre_id,genre_name):
    all_ch=[];seen=set();pg=0;total_known=0;ce=0
    while pg<1000:
        d,tok,url=req_page(portal,mac,tok,url,genre_id,pg)
        if not d:
            ce+=1
            if ce>=3: break
            pg+=1;time.sleep(0.5);continue
        js=d.get("js",{});data=js.get("data",[]) or [];total=int(js.get("total_items",0) or 0)
        if total>0 and total_known==0: total_known=total
        if not data:
            ce+=1
            if ce>=2: break
            pg+=1;time.sleep(0.5);continue
        ce=0
        for ch in data:
            ch["_group"]=genre_name
            ch_id=str(ch.get("id",""))
            if ch_id and ch_id in seen: continue
            if ch_id: seen.add(ch_id)
            all_ch.append(ch)
        print("  %s p%d: %d/%d"%(genre_name,pg,len(all_ch),total_known))
        if total_known>0 and len(all_ch)>=total_known: break
        pg+=1;time.sleep(0.15)
    return all_ch,tok,url

def count_all_pages(portal,mac,tok,url,genre_id,genre_name):
    d,tok,url=req_page(portal,mac,tok,url,genre_id,0)
    if d:
        js=d.get("js",{});total=int(js.get("total_items",0) or 0);data=js.get("data",[]) or []
        if total>0: return total,tok,url
        if data:
            count=len(data);pg=1
            while pg<500:
                d2,tok,url=req_page(portal,mac,tok,url,genre_id,pg)
                if not d2: break
                js2=d2.get("js",{});total2=int(js2.get("total_items",0) or 0);data2=js2.get("data",[]) or []
                if total2>0: return total2,tok,url
                if not data2: break
                count+=len(data2);pg+=1;time.sleep(0.1)
            return count,tok,url
    return 0,tok,url

def clean_link(cmd):
    if not cmd: return ""
    c=cmd.strip()
    for p in ["ffmpeg ","ffrt ","ffmpeg_exec "]:
        if c.startswith(p): c=c[len(p):]
    parts=c.split(" ")
    for p in parts:
        if p.startswith("http"): return p.strip()
    return c.strip()

def build_m3u(channels):
    lines=["#EXTM3U x-tvg-url=\"\""]
    for i,ch in enumerate(channels):
        name=(ch.get("name","") or "Ch%d"%(i+1)).strip()
        logo=ch.get("logo","") or "";group=ch.get("_group","Autres")
        num=str(ch.get("number",i+1));cmd=ch.get("cmd","") or ""
        link=clean_link(cmd)
        if not link: link=cmd.strip()
        if not link: link="http://0.0.0.0"
        lines.append('#EXTINF:-1 tvg-id="%s" tvg-name="%s" tvg-logo="%s" group-title="%s",%s'%(
            num,name.replace('"',"'"),logo,group.replace('"',"'"),name))
        lines.append(link)
    return "\n".join(lines)

def load_saved():
    os.makedirs(SAVE_DIR,exist_ok=True)
    if os.path.exists(SAVE_FILE):
        try: return json.load(open(SAVE_FILE,encoding="utf-8"))
        except: pass
    return []

def save_connexion(name,portal,mac):
    data=load_saved()
    for item in data:
        if item.get("portal")==portal and item.get("mac")==mac:
            item["name"]=name;item["date"]=datetime.now().strftime("%d/%m/%Y %H:%M")
            json.dump(data,open(SAVE_FILE,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
            return "updated"
    data.append({"name":name,"portal":portal,"mac":mac,"date":datetime.now().strftime("%d/%m/%Y %H:%M")})
    json.dump(data,open(SAVE_FILE,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
    return "saved"

def delete_connexion(idx):
    data=load_saved()
    if 0<=idx<len(data):
        data.pop(idx)
        json.dump(data,open(SAVE_FILE,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
        return True
    return False

def do_convert(portal,mac,selected_cats):
    global G
    G={"pct":1,"msg":"Initialisation...","done":False,"error":"","channels":0,"categories":0,"size_kb":0,"filepath":"","running":True}
    time.sleep(0.3)
    try:
        upd(5,"Connexion...");tok,lu=new_tok(portal,mac)
        if not tok:
            log_connexion(portal,mac,succes=False)
            G["error"]="Authentification impossible.";G["done"]=True;G["running"]=False;return
        log_connexion(portal,mac,succes=True)
        upd(10,"Profil...");do_prof(lu,mac,tok)
        upd(15,"Categories...");cats=get_cats(lu,mac,tok)
        if selected_cats and selected_cats!=["all"]:
            cats_to_use=[c for c in cats if str(c.get("id","")) in selected_cats]
            if not cats_to_use: cats_to_use=cats
        else: cats_to_use=cats
        total_cats=len(cats_to_use);upd(18,"%d categories..."%total_cats)
        all_channels=[];seen_ids=set()
        for ci,cat in enumerate(cats_to_use):
            cat_id=cat.get("id","*");cat_name=cat.get("title",cat.get("name","Autres"))
            pct=20+int((ci/max(total_cats,1))*65)
            upd(pct,"[%d/%d] %s — %d ch"%(ci+1,total_cats,str(cat_name),len(all_channels)))
            if ci%5==0 and ci>0:
                tok2,lu2=new_tok(portal,mac)
                if tok2: tok=tok2;lu=lu2;do_prof(lu,mac,tok);time.sleep(0.5)
            ch_cat,tok,lu=get_all_pages(portal,mac,tok,lu,cat_id,str(cat_name))
            added=0
            for ch in ch_cat:
                ch_id=str(ch.get("id",""))
                if ch_id and ch_id in seen_ids: continue
                if ch_id: seen_ids.add(ch_id)
                all_channels.append(ch);added+=1
        total=len(all_channels)
        if not all_channels:
            G["error"]="Aucune chaine trouvee.";G["done"]=True;G["running"]=False;return
        upd(87,"%d chaines ! M3U..."%total);m3u=build_m3u(all_channels)
        upd(95,"Sauvegarde...")
        os.makedirs(OUTPUT_DIR,exist_ok=True)
        fp=os.path.join(OUTPUT_DIR,"playlist_"+datetime.now().strftime("%Y%m%d_%H%M%S")+".m3u")
        with open(fp,"w",encoding="utf-8") as f: f.write(m3u)
        last_file["path"]=fp;sk=round(os.path.getsize(fp)/1024,1)
        G["pct"]=100;G["msg"]="Termine ! %d chaines"%total
        G["channels"]=total;G["categories"]=total_cats;G["size_kb"]=sk;G["filepath"]=fp
        G["done"]=True;G["running"]=False
    except Exception as e:
        import traceback;traceback.print_exc()
        G["error"]=str(e);G["done"]=True;G["running"]=False

HTML = r"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>MAC to M3U</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Arial;background:#0d1117;min-height:100vh;padding:15px;color:#fff}
.wrap{max-width:700px;margin:0 auto}
h1{text-align:center;color:#00d4ff;font-size:22px;padding:20px 0 15px}
.box{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px;margin-bottom:15px}
.box-title{font-size:16px;font-weight:bold;margin-bottom:15px;padding-bottom:10px;border-bottom:1px solid #30363d}
label{color:#8b949e;font-size:13px;display:block;margin-bottom:4px;margin-top:10px}
label:first-of-type{margin-top:0}
input[type=text]{width:100%;padding:10px 14px;border-radius:8px;border:1px solid #30363d;background:#0d1117;color:#fff;font-size:14px;outline:none}
input[type=text]:focus{border-color:#00d4ff}
input[type=text]::placeholder{color:#484f58}
input[type=file]{width:100%;padding:10px;border-radius:8px;border:1px solid #30363d;background:#0d1117;color:#fff;font-size:13px;margin-top:8px}
.btn{display:block;width:100%;padding:12px;border-radius:8px;font-size:14px;font-weight:bold;cursor:pointer;border:none;margin-top:8px;color:#fff;text-align:center;text-decoration:none;transition:opacity .2s}
.btn:hover:not(:disabled){opacity:.85}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn-blue{background:#0f3460}
.btn-purple{background:linear-gradient(135deg,#7b2ff7,#0f3460)}
.btn-green{background:#1a7f37}
.btn-gold{background:linear-gradient(135deg,#d4a017,#b8860b);color:#000 !important;font-size:15px !important;padding:14px !important}
.btn-cyan{background:linear-gradient(135deg,#00d4ff,#0088aa);color:#000 !important}
.btn-orange{background:#c47a00}
.btn-sm{padding:8px 14px;border-radius:7px;font-size:12px;font-weight:bold;cursor:pointer;border:none;color:#fff;display:inline-block;width:auto;margin:0}
.ok{margin-top:12px;padding:13px;border-radius:10px;background:rgba(26,127,55,0.1);border:1px solid #1a7f37;color:#3fb950;font-size:13px;line-height:2}
.err{margin-top:12px;padding:13px;border-radius:10px;background:rgba(185,28,28,0.1);border:1px solid #b91c1c;color:#f85149;font-size:13px}
.dl-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.dl-btn{flex:1;min-width:130px;padding:12px;border-radius:8px;font-size:13px;font-weight:bold;text-align:center;text-decoration:none;color:#fff;display:block}
.conn-card{background:#0d1117;border:1px solid #30363d;border-radius:10px;padding:14px;margin-bottom:8px}
.conn-card:hover{border-color:#58a6ff}
.conn-name{font-size:15px;font-weight:bold;color:#fff}
.conn-url{font-size:12px;color:#8b949e;margin-top:3px;word-break:break-all}
.conn-mac{font-size:12px;color:#58a6ff;margin-top:2px}
.conn-date{font-size:11px;color:#484f58;margin-top:4px}
.conn-btns{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.conn-empty{text-align:center;color:#484f58;padding:25px;font-size:13px;background:#0d1117;border-radius:10px;border:1px dashed #30363d}
.cat-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px;max-height:300px;overflow-y:auto;margin-top:8px}
.ci{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:8px;background:#0d1117;border:1px solid #30363d;cursor:pointer}
.ci:hover{border-color:#58a6ff}.ci.sel{background:rgba(88,166,255,0.1);border-color:#58a6ff}
.ci input{accent-color:#58a6ff;width:15px;height:15px;cursor:pointer;flex-shrink:0}
.cn{color:#ccc;font-size:12px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cc{font-size:11px;padding:2px 7px;border-radius:5px;font-weight:bold;white-space:nowrap}
.cok{color:#58a6ff;background:rgba(88,166,255,0.1)}.cq{color:#f0883e;background:rgba(240,136,62,0.1)}
.cat-bar{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.cbs{padding:7px 13px;border-radius:7px;font-size:12px;font-weight:bold;cursor:pointer;border:none;color:#fff}
.cat-search{width:100%;padding:8px 12px;border-radius:8px;border:1px solid #30363d;background:#0d1117;color:#fff;font-size:13px;margin-bottom:8px;outline:none}
.sel-info{text-align:center;color:#58a6ff;font-size:12px;margin-top:8px;padding:7px;background:rgba(88,166,255,0.07);border-radius:8px;font-weight:bold}
.prog-bg{width:100%;height:26px;background:#0d1117;border-radius:13px;overflow:hidden;margin:10px 0}
.prog-fill{height:100%;width:0%;border-radius:13px;background:linear-gradient(90deg,#00d4ff,#7b2ff7);transition:width .2s}
.prog-fill.done{background:linear-gradient(90deg,#00cc66,#007733)}
.prog-fill.err{background:#b91c1c}
.prog-top{display:flex;justify-content:space-between;align-items:center}
.prog-lbl{color:#8b949e;font-size:13px;font-weight:bold}
.prog-pct{color:#00d4ff;font-size:22px;font-weight:bold}
.prog-msg{text-align:center;color:#8b949e;font-size:12px;margin-top:6px;min-height:16px}
.stats-row{display:flex;justify-content:space-around;margin-top:14px}
.stat-box{text-align:center}
.stat-num{color:#58a6ff;font-size:22px;font-weight:bold}
.stat-lbl{color:#484f58;font-size:11px}
.note{background:rgba(255,153,0,0.08);border:1px solid #c47a00;border-radius:8px;padding:10px;font-size:12px;color:#f0883e;margin-top:8px}
</style>
</head><body><div class="wrap">
<h1>📡 MAC to M3U Converter</h1>

<div class="box">
  <div class="box-title">🔌 Connexion au portail</div>
  <label>🌐 URL du Portail</label>
  <input id="sp" type="text" placeholder="http://exemple.com:8080">
  <label>📟 Adresse MAC</label>
  <input id="sm" type="text" placeholder="00:1A:79:XX:XX:XX">
  <button class="btn btn-blue" id="btnLoad" onclick="chargerCats()">📂 Charger les catégories</button>
</div>

<div class="box" style="border:2px solid #d4a017">
  <div class="box-title" style="color:#d4a017">💾 Sauvegarder cette connexion</div>
  <div class="note">⚠️ Sur Render.com les sauvegardes sont temporaires. Téléchargez connexions.json pour les garder.</div>
  <label>📝 Nom de la connexion</label>
  <input id="connName" type="text" placeholder="Ex: Mon IPTV, Portail Principal...">
  <button class="btn btn-gold" onclick="sauvegarderConn()">💾 SAUVEGARDER CETTE CONNEXION</button>
</div>

<div class="box" style="border:2px solid #00d4ff">
  <div class="box-title" style="color:#00d4ff">📥 Télécharger &amp; Restaurer</div>
  <div class="dl-row">
    <a href="/dl_script" class="dl-btn btn-purple">⬇️ Télécharger<br>mac2m3u.py</a>
    <a href="/dl_save"   class="dl-btn btn-cyan">⬇️ Télécharger<br>connexions.json</a>
  </div>
  <div style="margin-top:15px;padding-top:15px;border-top:1px solid #30363d">
    <div style="color:#00d4ff;font-size:14px;font-weight:bold;margin-bottom:8px">🔄 Restaurer connexions.json</div>
    <input type="file" id="restoreFile" accept=".json">
    <button class="btn btn-cyan" onclick="restaurer()" style="margin-top:8px">🔄 Restaurer depuis ce fichier</button>
    <div id="restoreMsg"></div>
  </div>
</div>

<div class="box">
  <div class="box-title">📋 Mes connexions sauvegardées <span id="connCount" style="color:#8b949e;font-weight:normal;font-size:12px"></span></div>
  <div id="connList"><div class="conn-empty">⏳ Chargement...</div></div>
</div>

<div class="box" id="boxCats" style="display:none">
  <div class="box-title">📺 Catégories <small id="catCnt" style="color:#8b949e;font-weight:normal;font-size:12px"></small></div>
  <div class="cat-bar">
    <button class="cbs" style="background:#1a7f37" onclick="sAll()">✅ Tout</button>
    <button class="cbs" style="background:#444" onclick="dAll()">❌ Aucun</button>
    <button class="cbs" style="background:#0f3460" onclick="inv()">🔄 Inverser</button>
    <button class="cbs btn-orange" onclick="sNZ()">🚫 Sans ?</button>
  </div>
  <input class="cat-search" id="catSearch" type="text" placeholder="🔍 Rechercher...">
  <div class="cat-grid" id="catGrid"></div>
  <div class="sel-info" id="selInfo">0 catégorie sélectionnée</div>
  <button class="btn btn-purple" id="btnConv" onclick="convertirSel()" style="margin-top:12px">🚀 Convertir les catégories sélectionnées</button>
  <button class="btn btn-green" onclick="convertirTout()">🌍 Convertir TOUTES les catégories</button>
</div>

<div class="box" id="boxProg" style="display:none">
  <div class="box-title">⚙️ Progression</div>
  <div class="prog-top">
    <span class="prog-lbl" id="pLbl">En attente...</span>
    <span class="prog-pct" id="pPct">0%</span>
  </div>
  <div class="prog-bg"><div class="prog-fill" id="pFill"></div></div>
  <div class="prog-msg" id="pMsg"></div>
  <div id="pRes"></div>
</div>

<script>
var CATS=[], TM=null;
window.onload=function(){
  var p=localStorage.getItem("p")||"", m=localStorage.getItem("m")||"";
  if(p) document.getElementById("sp").value=p;
  if(m) document.getElementById("sm").value=m;
  document.getElementById("catSearch").oninput=filtrer;
  chargerListe();
};
function savL(){
  var p=document.getElementById("sp").value, m=document.getElementById("sm").value;
  if(p) localStorage.setItem("p",p.trim());
  if(m) localStorage.setItem("m",m.trim());
}
function sauvegarderConn(){
  var name=document.getElementById("connName").value.trim();
  var portal=document.getElementById("sp").value.trim();
  var mac=document.getElementById("sm").value.trim();
  if(!name){ alert("⚠️ Donnez un nom !"); return; }
  if(!portal||!mac){ alert("⚠️ Remplissez URL et MAC !"); return; }
  var xhr=new XMLHttpRequest();
  xhr.open("POST","/save_conn",true);
  xhr.setRequestHeader("Content-Type","application/x-www-form-urlencoded");
  xhr.onload=function(){
    if(xhr.status===200){
      var d=JSON.parse(xhr.responseText);
      if(d.ok){ document.getElementById("connName").value=""; alert("✅ Sauvegardé !"); chargerListe(); }
    }
  };
  xhr.send("name="+encodeURIComponent(name)+"&portal="+encodeURIComponent(portal)+"&mac="+encodeURIComponent(mac));
}
function chargerListe(){
  var xhr=new XMLHttpRequest();
  xhr.open("GET","/get_conns",true);
  xhr.onload=function(){
    if(xhr.status===200){ try{ afficherConnexions(JSON.parse(xhr.responseText)); }catch(e){} }
  };
  xhr.send();
}
function afficherConnexions(data){
  var list=document.getElementById("connList");
  var cnt=document.getElementById("connCount");
  if(!data||data.length===0){
    list.innerHTML="<div class='conn-empty'>Aucune connexion sauvegardée.</div>";
    if(cnt) cnt.textContent=""; return;
  }
  if(cnt) cnt.textContent="("+data.length+")";
  list.innerHTML="";
  data.forEach(function(item,i){
    var div=document.createElement("div");
    div.className="conn-card";
    div.innerHTML=
      "<div class='conn-name'>"+item.name+"</div>"+
      "<div class='conn-url'>🌐 "+item.portal+"</div>"+
      "<div class='conn-mac'>📟 "+item.mac+"</div>"+
      "<div class='conn-date'>📅 "+item.date+"</div>"+
      "<div class='conn-btns'>"+
        "<button class='btn-sm' style='background:#1a7f37' onclick='utiliserConn("+JSON.stringify(item.portal)+","+JSON.stringify(item.mac)+","+JSON.stringify(item.name)+")'>🔄 Utiliser</button>"+
        "<button class='btn-sm' style='background:#b91c1c' onclick='supprimerConn("+i+")'>🗑️</button>"+
      "</div>";
    list.appendChild(div);
  });
}
function utiliserConn(portal,mac,name){
  document.getElementById("sp").value=portal;
  document.getElementById("sm").value=mac;
  localStorage.setItem("p",portal);
  localStorage.setItem("m",mac);
  window.scrollTo({top:0,behavior:"smooth"});
  alert("✅ \""+name+"\" restaurée !\nCliquez sur 📂 Charger les catégories.");
}
function supprimerConn(idx){
  if(!confirm("Supprimer ?")) return;
  var xhr=new XMLHttpRequest();
  xhr.open("POST","/del_conn",true);
  xhr.setRequestHeader("Content-Type","application/x-www-form-urlencoded");
  xhr.onload=function(){ chargerListe(); };
  xhr.send("idx="+idx);
}
function restaurer(){
  var file=document.getElementById("restoreFile").files[0];
  if(!file){ alert("⚠️ Sélectionnez un fichier !"); return; }
  var fd=new FormData(); fd.append("file",file);
  var xhr=new XMLHttpRequest();
  xhr.open("POST","/restore_save",true);
  xhr.onload=function(){
    if(xhr.status===200){
      try{
        var d=JSON.parse(xhr.responseText);
        var msg=document.getElementById("restoreMsg");
        if(d.ok){ msg.innerHTML="<div class='ok'>✅ "+d.count+" connexion(s) restaurée(s) !</div>"; chargerListe(); document.getElementById("restoreFile").value=""; }
        else{ msg.innerHTML="<div class='err'>❌ "+d.msg+"</div>"; }
      }catch(e){}
    }
  };
  xhr.send(fd);
}
function setBar(pct,lbl,msg,cls){
  document.getElementById("boxProg").style.display="block";
  document.getElementById("pFill").style.width=pct+"%";
  document.getElementById("pPct").textContent=pct+"%";
  document.getElementById("pLbl").textContent=lbl;
  document.getElementById("pMsg").textContent=msg;
  document.getElementById("pFill").className="prog-fill "+(cls||"");
}
function startPoll(){
  if(TM) clearInterval(TM);
  TM=setInterval(function(){
    var r=new XMLHttpRequest();
    r.open("GET","/progress",true);
    r.setRequestHeader("Cache-Control","no-cache");
    r.onload=function(){
      try{
        var d=JSON.parse(r.responseText);
        var cls=d.done?(d.error?"err":"done"):"";
        setBar(d.pct,"Progression : "+d.pct+"%",d.msg,cls);
        if(d.done){
          clearInterval(TM);TM=null;
          document.getElementById("btnConv").disabled=false;
          document.getElementById("btnConv").textContent="🚀 Convertir les catégories sélectionnées";
          document.getElementById("btnLoad").disabled=false;
          document.getElementById("btnLoad").textContent="📂 Charger les catégories";
          if(d.error){
            document.getElementById("pRes").innerHTML="<div class='err'>❌ "+d.error+"</div>";
          }else if(d.channels>0){
            document.getElementById("pRes").innerHTML=
              "<div class='ok'>✅ Conversion réussie !<br>📺 Chaînes : <b>"+d.channels+"</b><br>📂 Catégories : <b>"+d.categories+"</b><br>💾 Taille : <b>"+d.size_kb+" Ko</b></div>"+
              "<div class='stats-row'>"+
              "<div class='stat-box'><div class='stat-num'>"+d.channels+"</div><div class='stat-lbl'>Chaînes</div></div>"+
              "<div class='stat-box'><div class='stat-num'>"+d.categories+"</div><div class='stat-lbl'>Catégories</div></div>"+
              "<div class='stat-box'><div class='stat-num'>"+d.size_kb+"</div><div class='stat-lbl'>Ko</div></div>"+
              "</div>"+
              "<a href='/download' class='btn btn-green' style='margin-top:12px'>⬇️ Télécharger M3U</a>";
          }
        }
      }catch(e){}
    };
    r.send();
  },300);
}
function chargerCats(){
  var portal=document.getElementById("sp").value.trim();
  var mac=document.getElementById("sm").value.trim();
  if(!portal||!mac){ alert("⚠️ Remplissez URL et MAC !"); return; }
  savL();
  var btn=document.getElementById("btnLoad");
  btn.disabled=true; btn.textContent="⏳ Chargement...";
  document.getElementById("pRes").innerHTML="";
  setBar(2,"Connexion...","Chargement des catégories...","");
  startPoll();
  var xhr=new XMLHttpRequest();
  xhr.open("POST","/get_cats",true);
  xhr.setRequestHeader("Content-Type","application/x-www-form-urlencoded");
  xhr.onload=function(){
    if(xhr.status===200){
      try{
        var d=JSON.parse(xhr.responseText);
        if(d.error){ setBar(0,"Erreur",d.error,"err"); alert("❌ "+d.error); btn.disabled=false; btn.textContent="📂 Charger les catégories"; return; }
        CATS=d.cats; afficherCats(CATS);
        document.getElementById("boxCats").style.display="block";
        document.getElementById("catCnt").textContent="— "+CATS.length+" catégories";
        document.getElementById("boxCats").scrollIntoView({behavior:"smooth"});
      }catch(e){ alert("Erreur: "+e.message); }
    }
  };
  xhr.onerror=function(){ btn.disabled=false; btn.textContent="📂 Charger les catégories"; };
  xhr.send("portal="+encodeURIComponent(portal)+"&mac="+encodeURIComponent(mac));
}
function afficherCats(cats){
  var grid=document.getElementById("catGrid"); grid.innerHTML="";
  cats.forEach(function(c){
    var div=document.createElement("div");
    div.className="ci";
    div.setAttribute("data-id",c.id);
    div.setAttribute("data-name",c.name.toLowerCase());
    div.setAttribute("data-count",c.count);
    var ccls=c.count>0?"cc cok":"cc cq";
    var ctxt=c.count>0?String(c.count):"?";
    div.innerHTML="<input type='checkbox' value='"+c.id+"'><span class='cn' title='"+c.name+"'>"+c.name+"</span><span class='"+ccls+"'>"+ctxt+"</span>";
    div.addEventListener("click",function(e){
      if(e.target.tagName!=="INPUT"){ var cb=this.querySelector("input"); cb.checked=!cb.checked; }
      this.classList.toggle("sel",this.querySelector("input").checked);
      majSel();
    });
    grid.appendChild(div);
  });
  majSel();
}
function filtrer(){
  var q=document.getElementById("catSearch").value.toLowerCase();
  document.querySelectorAll(".ci").forEach(function(el){ el.style.display=el.getAttribute("data-name").includes(q)?"":"none"; });
}
function sAll(){ document.querySelectorAll(".ci").forEach(function(el){ if(el.style.display!=="none"){ el.querySelector("input").checked=true; el.classList.add("sel"); } }); majSel(); }
function dAll(){ document.querySelectorAll(".ci input").forEach(function(cb){ cb.checked=false; cb.closest(".ci").classList.remove("sel"); }); majSel(); }
function inv(){ document.querySelectorAll(".ci").forEach(function(el){ if(el.style.display!=="none"){ var cb=el.querySelector("input"); cb.checked=!cb.checked; el.classList.toggle("sel",cb.checked); } }); majSel(); }
function sNZ(){ document.querySelectorAll(".ci").forEach(function(el){ var n=parseInt(el.getAttribute("data-count")||"0"); var cb=el.querySelector("input"); if(n>0){cb.checked=true;el.classList.add("sel");}else{cb.checked=false;el.classList.remove("sel");} }); majSel(); }
function majSel(){ var n=document.querySelectorAll(".ci input:checked").length; var t=document.querySelectorAll(".ci input").length; document.getElementById("selInfo").textContent=n+" / "+t+" catégorie(s) sélectionnée(s)"; }
function getIds(){ var ids=[]; document.querySelectorAll(".ci input:checked").forEach(function(cb){ids.push(cb.value);}); return ids; }
function convertirSel(){ var ids=getIds(); if(!ids.length){ alert("⚠️ Sélectionnez au moins une catégorie !"); return; } lancerConv(ids); }
function convertirTout(){ lancerConv(["all"]); }
function lancerConv(ids){
  var portal=document.getElementById("sp").value.trim();
  var mac=document.getElementById("sm").value.trim();
  if(!portal||!mac){ alert("⚠️ Remplissez URL et MAC !"); return; }
  savL();
  document.getElementById("pRes").innerHTML="";
  document.getElementById("btnConv").disabled=true;
  document.getElementById("btnConv").textContent="⏳ Conversion en cours...";
  setBar(1,"Démarrage...","Préparation...","");
  document.getElementById("boxProg").scrollIntoView({behavior:"smooth"});
  startPoll();
  setTimeout(function(){
    var xhr=new XMLHttpRequest();
    xhr.open("POST","/start",true);
    xhr.setRequestHeader("Content-Type","application/x-www-form-urlencoded");
    xhr.send("portal="+encodeURIComponent(portal)+"&mac="+encodeURIComponent(mac)+"&cats="+encodeURIComponent(JSON.stringify(ids)));
  },200);
}
</script>
</div></body></html>"""

@app.route("/")
def index(): return HTML

@app.route("/dl_script")
def dl_script():
    fp=os.path.abspath(__file__)
    return send_file(fp,as_attachment=True,download_name="mac2m3u.py",mimetype="text/plain")

@app.route("/dl_save")
def dl_save():
    if not os.path.exists(SAVE_FILE): return "Aucune sauvegarde.",404
    return send_file(SAVE_FILE,as_attachment=True,download_name="connexions.json",mimetype="application/json")

@app.route("/admin/log")
def admin_log():
    if not os.path.exists(LOG_FILE): return "Aucun historique.",404
    return send_file(LOG_FILE,as_attachment=True,download_name="historique_connexions.txt",mimetype="text/plain")

@app.route("/restore_save",methods=["POST"])
def restore_save():
    try:
        f=request.files.get("file")
        if not f: return Response(json.dumps({"ok":False,"msg":"Aucun fichier"}),mimetype="application/json")
        data=json.loads(f.read().decode("utf-8"))
        if not isinstance(data,list): return Response(json.dumps({"ok":False,"msg":"Format invalide"}),mimetype="application/json")
        os.makedirs(SAVE_DIR,exist_ok=True)
        json.dump(data,open(SAVE_FILE,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
        return Response(json.dumps({"ok":True,"count":len(data)}),mimetype="application/json")
    except Exception as e:
        return Response(json.dumps({"ok":False,"msg":str(e)}),mimetype="application/json")

@app.route("/save_conn",methods=["POST"])
def save_conn():
    name=request.form.get("name","").strip()
    portal=request.form.get("portal","").strip()
    mac=request.form.get("mac","").strip()
    if not name or not portal or not mac:
        return Response(json.dumps({"ok":False}),mimetype="application/json")
    r=save_connexion(name,portal,mac)
    return Response(json.dumps({"ok":True,"result":r}),mimetype="application/json")

@app.route("/get_conns")
def get_conns():
    return Response(json.dumps(load_saved()),mimetype="application/json")

@app.route("/del_conn",methods=["POST"])
def del_conn():
    try: idx=int(request.form.get("idx","-1"))
    except: idx=-1
    return Response(json.dumps({"ok":delete_connexion(idx)}),mimetype="application/json")

@app.route("/get_cats",methods=["POST"])
def get_cats_route():
    global G
    portal=request.form.get("portal","").strip()
    mac=request.form.get("mac","").strip()
    G={"pct":5,"msg":"Connexion...","done":False,"error":"","channels":0,"categories":0,"size_kb":0,"filepath":"","running":True}
    upd(5,"Connexion...")
    tok,url=new_tok(portal,mac)
    if not tok:
        log_connexion(portal,mac,succes=False)
        G["running"]=False;G["done"]=True
        return Response(json.dumps({"error":"Connexion impossible."}),mimetype="application/json")
    log_connexion(portal,mac,succes=True)
    upd(15,"Profil...");do_prof(url,mac,tok)
    upd(25,"Categories...")
    cats=get_cats(url,mac,tok)
    if not cats:
        G["running"]=False;G["done"]=True
        return Response(json.dumps({"error":"Aucune categorie trouvee."}),mimetype="application/json")
    total_c=len(cats);result=[]
    for i,c in enumerate(cats):
        cat_id=c.get("id","");cat_name=c.get("title",c.get("name","?"))
        pct=30+int((i/max(total_c,1))*65)
        upd(pct,"Comptage %d/%d: %s"%(i+1,total_c,str(cat_name)))
        if i%20==0 and i>0:
            tok2,url2=new_tok(portal,mac)
            if tok2: tok=tok2;url=url2
        count,tok,url=count_all_pages(portal,mac,tok,url,cat_id,str(cat_name))
        result.append({"id":str(cat_id),"name":str(cat_name),"count":count})
    upd(100,"%d categories !"%len(result))
    G["running"]=False;G["done"]=True
    return Response(json.dumps({"cats":result}),mimetype="application/json")

@app.route("/start",methods=["POST"])
def start():
    portal=request.form.get("portal","").strip()
    mac=request.form.get("mac","").strip()
    cats_json=request.form.get("cats","[\"all\"]")
    try: selected=json.loads(cats_json)
    except: selected=["all"]
    t=threading.Thread(target=do_convert,args=(portal,mac,selected))
    t.daemon=True;t.start()
    return "OK"

@app.route("/progress")
def progress():
    return Response(json.dumps(G),mimetype="application/json",
        headers={"Cache-Control":"no-cache, no-store, must-revalidate","Pragma":"no-cache","Expires":"0"})

@app.route("/download")
def download():
    fp=last_file.get("path")
    if not fp or not os.path.exists(fp): return "Aucun fichier.",404
    return send_file(fp,as_attachment=True,download_name=os.path.basename(fp),mimetype="audio/x-mpegurl")

if __name__=="__main__":
    os.makedirs(SAVE_DIR,exist_ok=True)
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    port=int(os.environ.get("PORT",5000))
    print("\n"+"="*55)
    print("🌐 Port : %d"%port)
    print("="*55+"\n")
    app.run(host="0.0.0.0",port=port,debug=False,threaded=True)
