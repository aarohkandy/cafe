// The example plan: the TEPEX chain exactly as the full simulator ran it (missions fe6a6e77 and e7209706).
// Positions are metres north/east of the site.
export const DATES = {
  "2023": { label: "7 March 2023", start: "2023-03-07T17:00:00Z", hours: [17], note: "one weather snapshot, held" },
  "2018": { label: "3 February 2018", start: "2018-02-03T14:00:00Z", hours: [12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], note: "hourly weather" },
};

export function defaultPlan(date = "2023") {
  return {
    site: [10.0, -95.0], date, start: new Date(DATES[date].start), hours: 2,
    glider: { start: [0, 0], goal: [2003.8, 0], band: [5, 100] },
    boat: { start: [-222.6, 0], tol: 300 },
    drone: { start: [-222.6, 54.8], minutes: 20, height: 30 },
    links: [
      { a: "glider", b: "boat", max: 1000, mode: "horizontal", need: 0.9 },
      { a: "boat", b: "drone", max: 300, mode: "3d", need: 0.95, until: 22 },
    ],
  };
}

export const NAMES = { glider: "Petrel", boat: "Tern", drone: "Gnat" };
export const KINDS = { glider: "glider", boat: "boat", drone: "drone" };
