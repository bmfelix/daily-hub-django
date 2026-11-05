// Song previews and live stations share one audio element, so only one thing plays at a time.
// What is playing is tracked by address, because the live homepage card replaces its buttons.
(function () {
  const audio = new Audio();
  let currentSrc = "";

  function show() {
    document.querySelectorAll("[data-src]").forEach((button) => {
      const playing = button.dataset.src === currentSrc && !audio.paused;
      button.setAttribute("aria-pressed", String(playing));
      if (button.dataset.src !== currentSrc) button.style.setProperty("--progress", 0);
    });
  }

  function stop() {
    audio.removeAttribute("src");
    audio.load();
    currentSrc = "";
    show();
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-src]");
    if (!button) return;
    const src = button.dataset.src;
    if (src === currentSrc && !audio.paused) {
      // A live station cannot be resumed from where it paused, so it stops instead.
      if ("live" in button.dataset) stop();
      else audio.pause();
      return;
    }
    if (src !== currentSrc) {
      currentSrc = src;
      audio.src = src;
    }
    audio.play().catch(() => {
      stop();
      button.disabled = true;
      button.title = "This could not be played.";
    });
  });

  audio.addEventListener("play", show);
  audio.addEventListener("pause", show);
  audio.addEventListener("ended", stop);
  audio.addEventListener("timeupdate", () => {
    if (!Number.isFinite(audio.duration)) return; // live stations have no end
    document.querySelectorAll("[data-src]").forEach((button) => {
      if (button.dataset.src === currentSrc) button.style.setProperty("--progress", (audio.currentTime / audio.duration) * 100);
    });
  });
  document.addEventListener("cards-updated", show);
})();
