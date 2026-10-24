// Live Radio card: the server pushes a new card over a WebSocket when a song changes.
(function () {
  if (!document.querySelector('[data-live-card="radio"]')) return;

  const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/radio/`;
  let delay = 1000;

  function connect() {
    const socket = new WebSocket(url);
    socket.addEventListener("open", () => { delay = 1000; });
    socket.addEventListener("message", (event) => {
      const card = document.querySelector('[data-live-card="radio"]');
      if (card) card.outerHTML = JSON.parse(event.data).html;
    });
    // Reconnect after a drop, waiting longer each time (up to 30 seconds).
    socket.addEventListener("close", () => {
      setTimeout(connect, delay);
      delay = Math.min(delay * 2, 30000);
    });
  }

  connect();
})();
