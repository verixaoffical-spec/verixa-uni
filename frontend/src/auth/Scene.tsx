// The decoration behind the glass card: a grid, a slowly turning hexagon, glowing orbs and film grain.
export default function Scene() {
  return (
    <div className="scene" aria-hidden="true">
      <div className="grid"></div>
      <svg className="hex" viewBox="0 0 100 100">
        <defs>
          <linearGradient id="hexStroke" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="hsl(249 76% 66%)" stopOpacity=".55" />
            <stop offset=".5" stopColor="#fff" stopOpacity=".05" />
            <stop offset="1" stopColor="hsl(174 62% 47%)" stopOpacity=".4" />
          </linearGradient>
        </defs>
        <path d="M50 4 89.8 27v46L50 96 10.2 73V27Z" />
        <path d="M50 16 79.4 33v34L50 84 20.6 67V33Z" opacity=".6" />
      </svg>
      <div className="orb a"></div><div className="orb b"></div><div className="orb c"></div>
      <div className="noise"></div>
    </div>
  );
}
