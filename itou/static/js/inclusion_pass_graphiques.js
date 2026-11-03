"use strict";

// Draws the impact charts of the pass inclusion "Pilotage" tab with the theme colours.
// Each chart reads its data from a json_script element and draws into a canvas of the same id.
(function () {
  const style = getComputedStyle(document.documentElement);
  const palette = ["--bs-primary", "--bs-accent-02", "--bs-accent-03", "--bs-accent-01"].map(
    (name) => style.getPropertyValue(name).trim()
  );
  const font = style.getPropertyValue("--bs-body-font-family").trim();

  Chart.defaults.font.family = font;
  Chart.defaults.color = palette[0];

  document.querySelectorAll("canvas[data-pass-graphique]").forEach((canvas) => {
    const graphique = JSON.parse(document.getElementById(canvas.dataset.passGraphique).textContent);
    const unite = graphique.unite || "";
    const isBar = graphique.type === "bar";
    new Chart(canvas, {
      type: graphique.type,
      data: {
        labels: graphique.series.map((serie) => serie.libelle),
        datasets: [
          {
            data: graphique.series.map((serie) => serie.nombre),
            backgroundColor: isBar ? palette[0] : palette,
            borderRadius: isBar ? 4 : 0,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        plugins: {
          legend: { display: !isBar, position: "bottom" },
          tooltip: {
            callbacks: { label: (context) => ` ${context.formattedValue}${unite ? " " + unite : ""}` },
          },
        },
        scales: isBar ? { y: { beginAtZero: true, max: 100, ticks: { callback: (value) => `${value} ${unite}` } } } : {},
      },
    });
  });
})();
