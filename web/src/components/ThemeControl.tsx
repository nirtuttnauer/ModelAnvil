import { useEffect, useState } from 'react';
import { SunMoon, SlidersHorizontal } from 'lucide-react';

type Theme = 'light' | 'dark' | 'system';

export function ThemeControl() {
  const [density, setDensity] = useState<'compact' | 'comfortable'>(() => localStorage.getItem('modelanvil_density') === 'comfortable' ? 'comfortable' : 'compact');
  useEffect(() => {
    document.documentElement.dataset.density = density;
    localStorage.setItem('modelanvil_density', density);
  }, [density]);
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
  return <>
    <label className="theme-control"><SunMoon size={16} aria-hidden="true" /><span>Theme</span><select aria-label="Color theme" value={theme} onChange={e => setTheme(e.target.value as Theme)}><option value="light">Light</option><option value="dark">Dark</option><option value="system">System</option></select></label>
    <label className="theme-control"><SlidersHorizontal size={16} aria-hidden="true" /><span>Density</span><select aria-label="Layout density" value={density} onChange={e => setDensity(e.target.value as 'compact' | 'comfortable')}><option value="compact">Compact</option><option value="comfortable">Comfortable</option></select></label>
  </>;
}
