import { useEffect, useState } from 'react';
import { SunMoon } from 'lucide-react';

type Theme = 'light' | 'dark' | 'system';

export function ThemeControl() {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem('modelanvil_theme');
    return saved === 'dark' || saved === 'system' ? saved : 'light';
  });
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const apply = () => { document.documentElement.dataset.theme = theme === 'system' ? (media.matches ? 'dark' : 'light') : theme; };
    apply();
    localStorage.setItem('modelanvil_theme', theme);
    media.addEventListener('change', apply);
    return () => media.removeEventListener('change', apply);
  }, [theme]);
  return <label className="theme-control"><SunMoon size={16} aria-hidden="true" /><select aria-label="Color theme" value={theme} onChange={e => setTheme(e.target.value as Theme)}><option value="light">Light</option><option value="dark">Dark</option><option value="system">System</option></select></label>;
}
