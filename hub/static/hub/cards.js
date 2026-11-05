// Homepage cards that need an outside service load after the page, so a slow service never holds it up.
// If one fails, the card keeps its short description.
(function () {
  async function fill(card, url) {
    try {
      const response = await fetch(url);
      if (response.ok) card.innerHTML = await response.text();
      if (card.dataset.cardEvery && !card.dataset.cardTimer) {
        card.dataset.cardTimer = "on";
        setInterval(() => fill(card, url), card.dataset.cardEvery * 1000);
      }
    } catch {
      // the description stays
    }
  }

  // Numbered buttons switch the Spotify player between playlists.
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-playlist]");
    if (!button) return;
    document.querySelector(".spotify-playlist").src = button.dataset.playlist;
    document.querySelectorAll("[data-playlist]").forEach((other) => {
      other.classList.toggle("is-chosen", other === button);
      other.setAttribute("aria-pressed", String(other === button));
    });
  });

  document.querySelectorAll("[data-card-url]").forEach((card) => {
    const url = new URL(card.dataset.cardUrl, window.location.href);
    if (!("locate" in card.dataset) || !navigator.geolocation) {
      fill(card, url);
      return;
    }
    navigator.geolocation.getCurrentPosition((position) => {
      url.searchParams.set("lat", position.coords.latitude.toFixed(2));
      url.searchParams.set("lon", position.coords.longitude.toFixed(2));
      fill(card, url);
    }, () => fill(card, url), { maximumAge: 600000, timeout: 10000 });
  });
})();
