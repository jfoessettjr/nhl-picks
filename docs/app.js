let DATA = null;

function $(id){ return document.getElementById(id); }

function setError(msg){
  const el = $("error");
  if (!msg){
    el.style.display = "none";
    el.textContent = "";
    return;
  }
  el.style.display = "block";
  el.textContent = msg;
}

function clearPicks(){
  $("picks").innerHTML = "";
  $("empty").style.display = "none";
}

function renderPick(p){
  const li = document.createElement("li");
  li.className = "pick";
  li.innerHTML = `
    <div class="pick-top">
      <div class="matchup">${p.away_name} @ ${p.home_name}</div>
      <div class="prob">${(p.win_prob*100).toFixed(1)}%</div>
    </div>
    <div class="pick-mid">
      <div class="winner">Pick: <strong>${p.pick_name}</strong></div>
      <div class="meta">Elo: ${Math.round(p.home_elo)} / ${Math.round(p.away_elo)} · HomeAdv: ${p.home_adv ? Math.round(p.home_adv) : "—"}</div>
    </div>
    <div class="pick-bot">
      <div class="factors">${p.factors}</div>
      <div class="why">
        <div class="why-title">Why this pick</div>
        <div class="why-grid">
          <div class="why-row"><div class="why-k">Base (no home ice)</div><div class="why-v">${(p.why.base*100).toFixed(1)}%</div></div>
          <div class="why-row"><div class="why-k">Home ice</div><div class="why-v">${p.why.home_ice_pp.toFixed(1)} pp</div></div>
          <div class="why-row"><div class="why-k">Recent form (L10)</div><div class="why-v">${p.why.form_pp.toFixed(1)} pp</div></div>
          <div class="why-row"><div class="why-k">Back-to-back fatigue</div><div class="why-v">${p.why.fatigue_pp.toFixed(1)} pp</div></div>
          <div class="why-row why-total"><div class="why-k">Final</div><div class="why-v">${(p.why.final*100).toFixed(1)}%</div></div>
        </div>
        <div class="why-note">
          Home/Away form: ${p.form_home} / ${p.form_away} pts ·
          Fatigue: ${p.fat_home} / ${p.fat_away} pts
        </div>
      </div>
    </div>
  `;
  return li;
}

function renderDate(d){
  clearPicks();
  setError(null);

  const block = DATA.by_date[d];
  $("title").textContent = `Picks for ${d}`;

  const note = $("buildNote");
  if (block && block.build_note){
    note.style.display = "inline-block";
    note.textContent = block.build_note;
  } else {
    note.style.display = "none";
  }

  if (!block || !block.picks || block.picks.length === 0){
    $("empty").style.display = "block";
    return;
  }

  const ol = $("picks");
  for (const p of block.picks){
    ol.appendChild(renderPick(p));
  }
}

function nearestAvailableDate(desired){
  if (!DATA) return desired;
  const dates = DATA.dates || [];
  if (dates.includes(desired)) return desired;
  return dates[0] || desired;
}

async function load(){
  try{
    const r = await fetch("./data/picks.json", {cache: "no-store"});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    DATA = await r.json();

    $("generatedAt").textContent = `Generated: ${DATA.generated_at || "unknown"}`;

    const dates = DATA.dates || [];
    const today = (new Date()).toISOString().slice(0,10);
    const initial = nearestAvailableDate(today);

    const dateInput = $("date");
    dateInput.value = initial;
    if (dates.length > 0){
      dateInput.min = dates[0];
      dateInput.max = dates[dates.length - 1];
    }

    renderDate(initial);

    $("btn").addEventListener("click", (e)=>{
      e.preventDefault();
      const d = dateInput.value;
      if (!d) return;
      renderDate(nearestAvailableDate(d));
    });

    dateInput.addEventListener("change", ()=>{
      const d = dateInput.value;
      if (!d) return;
      renderDate(nearestAvailableDate(d));
    });

  }catch(err){
    setError(`Could not load picks.json. Run the GitHub Action, or check docs/data/picks.json. Error: ${err}`);
  }
}

load();
