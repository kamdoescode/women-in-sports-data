// ════════════════════════════════════════════════
// DATA — from ecosystem_summary.csv
// ════════════════════════════════════════════════

const ecosystemData = [
  // WNBA
  { league: "WNBA", year: 2018, avg_views: 109665, total_views: 986986 },
  { league: "WNBA", year: 2019, avg_views: 5730456, total_views: 63035021 },
  { league: "WNBA", year: 2020, avg_views: 120093, total_views: 1321024 },
  { league: "WNBA", year: 2021, avg_views: 1048554, total_views: 17825411 },
  { league: "WNBA", year: 2022, avg_views: 965184, total_views: 29920704 },
  { league: "WNBA", year: 2023, avg_views: 7941232, total_views: 150883414 },
  { league: "WNBA", year: 2024, avg_views: 7568141, total_views: 227044222 },
  { league: "WNBA", year: 2025, avg_views: 3107791, total_views: 55940230 },
  // PWHL
  { league:"PWHL", year:2018, avg_views:0,      total_views:0        },
  { league:"PWHL", year:2019, avg_views:0,      total_views:0        },
  { league:"PWHL", year:2020, avg_views:0,      total_views:0        },
  { league:"PWHL", year:2021, avg_views:0,      total_views:0        },
  { league:"PWHL", year:2022, avg_views:0,      total_views:0        },
  { league:"PWHL", year:2023, avg_views:0,      total_views:0        },
  { league:"PWHL", year:2024, avg_views:330171, total_views:27404200  },
  { league:"PWHL", year:2025, avg_views:942299, total_views:68787800  },
  // Barclays WSL
  { league:"Barclays WSL", year:2018, avg_views:1197429,  total_views:89807158  },
  { league:"Barclays WSL", year:2019, avg_views:3481287, total_views:327240970  },
  { league:"Barclays WSL", year:2020, avg_views:1132367,  total_views:114369061  },
  { league:"Barclays WSL", year:2021, avg_views:7025864, total_views:716638127  },
  { league:"Barclays WSL", year:2022, avg_views:6347082, total_views:501419472 },
  { league:"Barclays WSL", year:2023, avg_views:12763657, total_views:1289129339 },
  { league:"Barclays WSL", year:2024, avg_views:6121515, total_views:606030011 },
  { league:"Barclays WSL", year:2025, avg_views:9911533, total_views:1020887870 },
];


const leagueColors = {
  "WNBA":                   "var(--wnba)",
  "PWHL":                   "var(--pwhl)",
  "Barclays WSL":           "var(--wsl)",
};

const leagueShort = {
  "WNBA": "WNBA",
  "PWHL": "PWHL",
  "Barclays WSL": "WSL",
};

// ---------- Code written by Claude AI Sonnet 4.6 ------------------------------ 
// ── Progress bar ──────────────────────────────────────
window.addEventListener("scroll", () => {
  const pct = window.scrollY / (document.body.scrollHeight - window.innerHeight) * 100;
  document.getElementById("progress-bar").style.width = pct + "%";
});

// ── Tooltip helper ────────────────────────────────────
const tooltip = document.getElementById("tooltip");
function showTip(html, x, y) {
  tooltip.innerHTML = html;
  tooltip.style.opacity = 1;
  tooltip.style.left = (x + 16) + "px";
  tooltip.style.top  = (y - 10) + "px";
}
function hideTip() { tooltip.style.opacity = 0; }

// ── Line Chart ────────────────────────────────────────
function drawLineChart() {
  const el = document.getElementById("line-chart");
  const W  = el.offsetWidth || 560;
  const margin = { top: 20, right: 80, bottom: 40, left: 60 };
  const width  = W - margin.left - margin.right;
  const height = 320 - margin.top - margin.bottom;

  const svg = d3.select("#line-chart").append("svg")
    .attr("width",  W)
    .attr("height", height + margin.top + margin.bottom)
    .append("g")
    .attr("transform", `translate(${margin.left},${margin.top})`);

  const leagues = [...new Set(ecosystemData.map(d => d.league))];
  const years   = [...new Set(ecosystemData.map(d => d.year))].sort();

  const x = d3.scaleLinear().domain(d3.extent(years)).range([0, width]);
  const y = d3.scaleLinear()
    .domain([0, d3.max(ecosystemData, d => d.avg_views) * 1.12])
    .range([height, 0]);

  // Grid
  svg.append("g").attr("class","grid")
    .call(d3.axisLeft(y).tickSize(-width).tickFormat("").ticks(5));

  // Axes
  svg.append("g").attr("class","axis")
    .attr("transform", `translate(0,${height})`)
    .call(d3.axisBottom(x).tickFormat(d3.format("d")).ticks(years.length));

  svg.append("g").attr("class","axis")
    .call(d3.axisLeft(y)
      .tickFormat(d => d >= 1e6 ? (d/1e6).toFixed(1)+"M" : d >= 1e3 ? (d/1e3).toFixed(0)+"K" : d)
      .ticks(5));

  const line = d3.line()
    .x(d => x(d.year))
    .y(d => y(d.avg_views))
    .curve(d3.curveMonotoneX);

  leagues.forEach(league => {
    const data = ecosystemData
      .filter(d => d.league === league && d.avg_views > 0)
      .sort((a,b) => a.year - b.year);

    const col = leagueColors[league];

    // Line path with draw animation
    const path = svg.append("path")
      .datum(data)
      .attr("fill","none")
      .attr("stroke", col)
      .attr("stroke-width", 2.5)
      .attr("d", line);

    const totalLength = path.node().getTotalLength();
    path
      .attr("stroke-dasharray", totalLength)
      .attr("stroke-dashoffset", totalLength)
      .transition().duration(1800).delay(300)
      .ease(d3.easeCubicInOut)
      .attr("stroke-dashoffset", 0);

    // Dots
    svg.selectAll(`.dot-${league.replace(/[\s()]/g,"_")}`)
      .data(data).enter().append("circle")
      .attr("cx", d => x(d.year))
      .attr("cy", d => y(d.avg_views))
      .attr("r", 4)
      .attr("fill", col)
      .attr("stroke", "var(--paper)")
      .attr("stroke-width", 2)
      .style("cursor","pointer")
      .on("mousemove", (event, d) => showTip(
        `<strong>${leagueShort[league]}</strong> ${d.year}<br>${d.avg_views.toLocaleString()} avg views`,
        event.clientX, event.clientY
      ))
      .on("mouseleave", hideTip);

    // End label
    const last = data[data.length - 1];
    if (last) {
      svg.append("text")
        .attr("x", x(last.year) + 8)
        .attr("y", y(last.avg_views))
        .attr("dominant-baseline","middle")
        .attr("fill", col)
        .attr("font-family","DM Mono, monospace")
        .attr("font-size", 10)
        .attr("letter-spacing","0.05em")
        .text(leagueShort[league]);
    }
  });
}

// ── Bar Chart (UK broadcast hours) ───────────────────
function drawBarChart() {
  const el = document.getElementById("bar-chart");
  const W  = Math.min(el.offsetWidth || 700, 820);
  const margin = { top: 20, right: 20, bottom: 40, left: 60 };
  const width  = W - margin.left - margin.right;
  const height = 260 - margin.top - margin.bottom;

  const svg = d3.select("#bar-chart").append("svg")
    .attr("width",  W)
    .attr("height", height + margin.top + margin.bottom)
    .append("g")
    .attr("transform", `translate(${margin.left},${margin.top})`);

  const x = d3.scaleBand()
    .domain(broadcastData.map(d => d.year))
    .range([0, width])
    .padding(0.35);

  const y = d3.scaleLinear()
    .domain([0, d3.max(broadcastData, d => d.hours) * 1.15])
    .range([height, 0]);

  svg.append("g").attr("class","grid")
    .call(d3.axisLeft(y).tickSize(-width).tickFormat("").ticks(4));

  svg.append("g").attr("class","axis")
    .attr("transform",`translate(0,${height})`)
    .call(d3.axisBottom(x).tickFormat(d3.format("d")));

  svg.append("g").attr("class","axis")
    .call(d3.axisLeft(y).ticks(4).tickFormat(d => d+"M"));

  svg.selectAll(".bar")
    .data(broadcastData).enter().append("rect")
    .attr("class","bar")
    .attr("x", d => x(d.year))
    .attr("width", x.bandwidth())
    .attr("y", height)
    .attr("height", 0)
    .attr("fill","var(--accent2)")
    .style("cursor","pointer")
    .on("mousemove", (event, d) => showTip(
      `<strong>${d.year}</strong><br>${d.hours}M viewing hours`,
      event.clientX, event.clientY
    ))
    .on("mouseleave", hideTip)
    .transition().duration(900).delay((d,i) => i * 80)
    .ease(d3.easeCubicOut)
    .attr("y", d => y(d.hours))
    .attr("height", d => height - y(d.hours));
}

// ── Intersection Observer for scroll animations ───────
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add("visible");
    }
  });
}, { threshold: 0.15 });

document.querySelectorAll(".step-card, .split-row").forEach(el => observer.observe(el));

// Animate split bars when visible
const splitObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.querySelectorAll(".split-bar-women").forEach(bar => {
        const pct = parseFloat(bar.closest(".split-row").dataset.pct);
        setTimeout(() => { bar.style.width = Math.min(pct, 100) + "%"; }, 200);
      });
      splitObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.3 });

const splitViz = document.getElementById("split-viz");
if (splitViz) splitObserver.observe(splitViz);

// ── Counter animation ─────────────────────────────────
function animateCounter(el, from, to, suffix) {
  const duration = 1500;
  const start = performance.now();
  function update(now) {
    const t = Math.min((now - start) / duration, 1);
    const ease = 1 - Math.pow(1 - t, 3);
    const val = Math.round(from + (to - from) * ease);
    el.textContent = val.toLocaleString() + suffix;
    if (t < 1) requestAnimationFrame(update);
  }
  requestAnimationFrame(update);
}

const counterEl = document.getElementById("counter-views");
const counterObs = new IntersectionObserver((entries) => {
  if (entries[0].isIntersecting) {
    const wnba2018 = ecosystemData.find(d => d.league === "WNBA" && d.year === 2018)?.avg_views || 38000;
    const wnba2025 = ecosystemData.find(d => d.league === "WNBA" && d.year === 2025)?.avg_views || 620000;
    animateCounter(counterEl, wnba2018, wnba2025, "");
    counterObs.unobserve(entries[0].target);
  }
}, { threshold: 0.5 });
counterObs.observe(counterEl);

// ── Init charts ───────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  drawLineChart();
  drawBarChart();
});

// Also draw immediately if DOM already loaded
if (document.readyState !== "loading") {
  drawLineChart();
  drawBarChart();
}

// --------- End of code written by Claude AI Sonnet 4.6 ------------------