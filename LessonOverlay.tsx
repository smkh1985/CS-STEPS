/**
 * LessonOverlay: the graphics laid over a lesson's screen recording (rendered with a transparent
 * background; lesson.py composites it). Everything is timed from the lesson's timing.json, which
 * lesson.py turns into the props below (seconds in the final video).
 *
 *  - intro: the CS-Steps background with animated cards, covering the screen until `intro.until`
 *  - sidebar: a progress panel on the right (current step glows, finished steps get a check)
 */
import React from 'react';
import {
  AbsoluteFill,
  Img,
  OffthreadVideo,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {BODY, C, MONO, TITLE, clamp, easeOut} from './common';

export type OverlayCard = {
  start: number;
  end: number;
  icon?: string; // an image in public/ (e.g. icons/vscode.svg), shown above the title
  title: string;
  subtitle?: string;
  chips?: string[];
  flow?: string[]; // boxes left to right, joined by arrows; the last one is shown as machine code
};

export type OverlayItem = {
  icon?: string; // an image in public/, shown before the title
  title: string;
  sub: string;
  appear: number; // when the row slides in
  active: [number, number]; // glowing while the narration is about it
  done: number; // when it gets its check
};

export type CameraMove = {
  start: number; // zooming in starts here...
  end: number; // ...and zooming out starts here
  region: [number, number, number, number]; // x, y, width, height (16:9) of the 1920x1080 screen
};

export type OverlayProps = {
  duration: number;
  intro?: {until: number};
  cards: OverlayCard[];
  sidebar?: {start: number; title: string; items: OverlayItem[]};
  preview?: string; // a screenshot behind everything, for checking the look only
  sidebarAway?: number; // 0..1: how far the sidebar has slid out (during camera zooms)
};

export type LessonVideoProps = OverlayProps & {
  video: string; // the screen recording, in public/
  camera: CameraMove[];
};

const ZOOM_IN = 0.8; // seconds
const ZOOM_OUT = 0.7;
const PAN = 0.8; // seconds to glide from one region straight into the next one

// ease in and out (smootherstep)
const smooth = (p: number) => p * p * p * (p * (p * 6 - 15) + 10);
// a zoom that starts where the previous one ends: pan between them instead of zooming out and in
const touches = (a?: CameraMove, b?: CameraMove) => !!a && !!b && b.start - a.end < 0.05;

/** How far into its region the camera is (0 = whole screen, 1 = region), and which region. */
const cameraAt = (t: number, camera: CameraMove[]) => {
  for (let i = 0; i < camera.length; i++) {
    const c = camera[i];
    const next = camera[i + 1];
    const panOut = touches(c, next);
    if (t < c.start || t > c.end + (panOut ? PAN : ZOOM_OUT)) continue;
    if (panOut && t >= c.end) {
      const k = smooth(interpolate(t, [c.end, c.end + PAN], [0, 1], clamp));
      const region = c.region.map((v, j) => v + (next!.region[j] - v) * k) as CameraMove['region'];
      return {p: 1, region};
    }
    const into = touches(camera[i - 1], c) ? 1 : interpolate(t, [c.start, c.start + ZOOM_IN], [0, 1], clamp);
    const out = panOut ? 1 : interpolate(t, [c.end, c.end + ZOOM_OUT], [1, 0], clamp);
    return {p: smooth(Math.min(into, out)), region: c.region};
  }
  return {p: 0, region: [0, 0, 1920, 1080] as CameraMove['region']};
};

/** The recording behind everything, with smooth camera zooms into regions of the screen. */
export const LessonVideo: React.FC<LessonVideoProps> = ({video, camera, ...overlay}) => {
  const {t} = useT();
  const {p, region} = cameraAt(t, camera);
  const [rx, ry, rw] = region;
  // the visible rectangle moves from the whole screen to the region; scale it up to fill 1920x1080
  const w = 1920 + (rw - 1920) * p;
  const x = rx * p;
  const y = ry * p;
  const s = 1920 / w;
  return (
    <AbsoluteFill style={{backgroundColor: '#000', overflow: 'hidden'}}>
      <AbsoluteFill style={{transformOrigin: '0 0', transform: `translate(${-x * s}px, ${-y * s}px) scale(${s})`}}>
        <OffthreadVideo src={staticFile(video)} muted style={{width: 1920, height: 1080}} />
      </AbsoluteFill>
      <LessonOverlay {...overlay} sidebarAway={p} />
    </AbsoluteFill>
  );
};

export const lessonVideoDefaults: LessonVideoProps = {duration: 10, cards: [], video: '', camera: []};

const useT = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return {t: frame / fps, fps, frame};
};

const pop = (t: number, at: number, fps: number, damping = 12) =>
  t < at ? 0 : spring({frame: (t - at) * fps, fps, config: {damping}});

/* ------------------------------------------------------------------ intro */

const IntroBackground: React.FC<{until: number}> = ({until}) => {
  const {t} = useT();
  const out = interpolate(t, [until - 0.6, until], [1, 0], clamp);
  if (out <= 0) return null;
  return (
    <AbsoluteFill
      style={{
        opacity: out,
        backgroundColor: C.BG,
        backgroundImage: [
          'radial-gradient(circle at 50% 45%, rgba(0,155,179,0.18), transparent 60%)',
          'linear-gradient(rgba(255,255,255,0.03) 2px, transparent 2px)',
          'linear-gradient(90deg, rgba(255,255,255,0.03) 2px, transparent 2px)',
        ].join(','),
        backgroundSize: '100% 100%, 90px 90px, 90px 90px',
      }}
    >
      <Img
        src={staticFile('CS-Steps-logo.svg')}
        style={{position: 'absolute', left: 30, bottom: 24, height: 70, opacity: 0.9}}
      />
    </AbsoluteFill>
  );
};

const Chip: React.FC<{text: string; at: number}> = ({text, at}) => {
  const {t, fps} = useT();
  const s = pop(t, at, fps, 11);
  return (
    <div
      style={{
        fontFamily: BODY,
        fontWeight: 800,
        fontSize: 40,
        color: C.BG,
        background: C.CYAN,
        borderRadius: 40,
        padding: '12px 34px',
        opacity: Math.min(1, s * 1.4),
        transform: `scale(${0.6 + 0.4 * s})`,
        boxShadow: '0 8px 30px rgba(58,215,240,0.35)',
        whiteSpace: 'nowrap',
      }}
    >
      {text}
    </div>
  );
};

const FlowBox: React.FC<{text: string; at: number; kind: 'in' | 'mid' | 'out'}> = ({text, at, kind}) => {
  const {t, fps} = useT();
  const s = pop(t, at, fps);
  const color = kind === 'mid' ? C.ORANGE : kind === 'out' ? C.GREEN : C.WHITE;
  return (
    <div
      style={{
        background: C.PANEL,
        border: `5px solid ${color}`,
        borderRadius: 22,
        padding: '26px 34px',
        fontFamily: kind === 'out' ? MONO : BODY,
        fontWeight: kind === 'out' ? 700 : 800,
        fontSize: kind === 'out' ? 46 : 40,
        color: kind === 'out' ? C.GREEN : C.WHITE,
        whiteSpace: 'nowrap',
        opacity: Math.min(1, s * 1.4),
        transform: `scale(${0.6 + 0.4 * s})`,
        boxShadow:
          kind === 'mid'
            ? `0 0 40px 4px rgba(255,128,8,${0.25 + 0.2 * Math.sin(t * 4)})`
            : '0 12px 40px rgba(0,0,0,0.45)',
      }}
    >
      {text}
    </div>
  );
};

const FlowArrow: React.FC<{at: number}> = ({at}) => {
  const {t} = useT();
  const p = easeOut(interpolate(t, [at, at + 0.5], [0, 1], clamp));
  const pulse = ((t - at) % 1.2) / 1.2;
  return (
    <div style={{width: 110, height: 30, position: 'relative', margin: '0 14px'}}>
      <div
        style={{position: 'absolute', left: 0, top: 12, height: 6, width: 86 * p, background: C.WHITE, borderRadius: 3}}
      />
      <div
        style={{
          position: 'absolute',
          left: 86 * p - 2,
          top: 0,
          width: 0,
          height: 0,
          borderTop: '15px solid transparent',
          borderBottom: '15px solid transparent',
          borderLeft: `24px solid ${C.WHITE}`,
          opacity: p > 0.02 ? 1 : 0,
        }}
      />
      {p >= 1 ? (
        <div
          style={{
            position: 'absolute',
            left: pulse * 80,
            top: 7,
            width: 16,
            height: 16,
            borderRadius: 8,
            background: C.CYAN,
            boxShadow: `0 0 24px 8px ${C.CYAN}`,
            opacity: 1 - pulse * 0.3,
          }}
        />
      ) : null}
    </div>
  );
};

const IntroCard: React.FC<{card: OverlayCard}> = ({card}) => {
  const {t, fps} = useT();
  if (t < card.start - 0.1 || t > card.end + 0.5) return null;
  const inP = pop(t, card.start, fps, 14);
  const outP = interpolate(t, [card.end, card.end + 0.4], [1, 0], clamp);
  const span = Math.max(1.5, card.end - card.start);
  const chips = card.chips ?? [];
  const flow = card.flow ?? [];
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', opacity: Math.min(1, inP * 1.3) * outP}}>
      <div
        style={{
          transform: `translateY(${(1 - inP) * 40}px)`,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 34,
        }}
      >
        {card.icon ? (
          <Img
            src={staticFile(card.icon)}
            style={{
              height: 190,
              marginBottom: -6,
              transform: `scale(${0.5 + 0.5 * pop(t, card.start + 0.15, fps, 9)}) rotate(${(1 - pop(t, card.start + 0.15, fps, 9)) * -25}deg)`,
              filter: 'drop-shadow(0 14px 40px rgba(0,122,204,0.55))',
            }}
          />
        ) : null}
        <div
          style={{
            fontFamily: TITLE,
            fontSize: 170,
            letterSpacing: 4,
            color: C.ORANGE,
            lineHeight: 0.9,
            textShadow: '0 10px 50px rgba(255,128,8,0.35)',
          }}
        >
          {card.title}
        </div>
        {card.subtitle ? (
          <div style={{fontFamily: BODY, fontWeight: 600, fontSize: 46, color: C.WHITE}}>{card.subtitle}</div>
        ) : null}
        {chips.length ? (
          <div style={{display: 'flex', gap: 22, marginTop: 20}}>
            {chips.map((c, i) => (
              <Chip key={c} text={c} at={card.start + 0.8 + (i * span * 0.6) / chips.length} />
            ))}
          </div>
        ) : null}
        {flow.length ? (
          <div style={{display: 'flex', alignItems: 'center', marginTop: 30}}>
            {flow.map((f, i) => {
              const at = card.start + 0.4 + (i * span * 0.7) / flow.length;
              return (
                <React.Fragment key={f}>
                  {i > 0 ? <FlowArrow at={at - 0.3} /> : null}
                  <FlowBox text={f} at={at} kind={i === 0 ? 'in' : i === flow.length - 1 ? 'out' : 'mid'} />
                </React.Fragment>
              );
            })}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

/* ---------------------------------------------------------------- sidebar */

const SIDEBAR = {right: 28, top: 250, width: 430};

const StepCircle: React.FC<{n: number; active: boolean; doneP: number}> = ({n, active, doneP}) => {
  const {t} = useT();
  const glow = active ? 0.55 + 0.45 * Math.sin(t * 5) : 0;
  return (
    <div style={{position: 'relative', width: 56, height: 56, flexShrink: 0}}>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: 28,
          border: `4px solid ${active ? C.CYAN : 'rgba(255,255,255,0.25)'}`,
          background: active ? 'rgba(58,215,240,0.12)' : 'rgba(255,255,255,0.04)',
          boxShadow: active
            ? `0 0 ${18 + 14 * glow}px ${4 + 4 * glow}px rgba(58,215,240,${0.35 + 0.3 * glow})`
            : 'none',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: BODY,
          fontWeight: 800,
          fontSize: 26,
          color: active ? C.CYAN : C.MUTED,
        }}
      >
        {n}
      </div>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: 28,
          background: C.GREEN,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: BODY,
          fontWeight: 800,
          fontSize: 32,
          color: C.BG,
          opacity: Math.min(1, doneP * 1.4),
          transform: `scale(${doneP}) rotate(${(1 - doneP) * -40}deg)`,
          boxShadow: doneP > 0 ? '0 0 22px 2px rgba(61,220,132,0.45)' : 'none',
        }}
      >
        ✓
      </div>
    </div>
  );
};

const Sidebar: React.FC<{sidebar: NonNullable<OverlayProps['sidebar']>; away?: number}> = ({sidebar, away = 0}) => {
  const {t, fps} = useT();
  if (t < sidebar.start || away >= 0.999) return null;
  const inP = easeOut(interpolate(t, [sidebar.start, sidebar.start + 0.7], [0, 1], clamp)) * (1 - away);
  const shown = sidebar.items.filter((it) => t >= it.appear - 0.05);
  const done = sidebar.items.filter((it) => t >= it.done).length;
  const progress = interpolate(done, [0, Math.max(1, shown.length)], [0, 1], clamp);
  return (
    <div
      style={{
        position: 'absolute',
        right: SIDEBAR.right,
        top: SIDEBAR.top,
        width: SIDEBAR.width,
        transform: `translateX(${(1 - inP) * (SIDEBAR.width + 60)}px)`,
        opacity: inP,
        background: 'linear-gradient(160deg, rgba(43,45,51,0.97), rgba(30,31,34,0.97))',
        border: '2px solid rgba(255,255,255,0.10)',
        borderRadius: 26,
        boxShadow: '0 24px 60px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.06)',
        padding: '26px 28px 24px',
        fontFamily: BODY,
        color: C.WHITE,
        overflow: 'hidden',
      }}
    >
      <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: 6, background: C.ORANGE}} />
      <div style={{fontFamily: TITLE, fontSize: 46, letterSpacing: 2, color: C.ORANGE, lineHeight: 1}}>
        {sidebar.title}
      </div>
      <div style={{height: 2, background: 'rgba(255,255,255,0.08)', margin: '16px 0 10px'}} />
      {shown.map((it, i) => {
        const rowIn = easeOut(interpolate(t, [it.appear, it.appear + 0.5], [0, 1], clamp));
        const active = t >= it.active[0] && t < it.active[1] && t < it.done;
        const doneP = pop(t, it.done, fps, 10);
        return (
          <div
            key={it.title}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 18,
              padding: '14px 12px',
              marginTop: 6,
              borderRadius: 18,
              background: active ? 'rgba(58,215,240,0.08)' : 'transparent',
              border: `2px solid ${active ? 'rgba(58,215,240,0.35)' : 'transparent'}`,
              opacity: rowIn,
              transform: `translateX(${(1 - rowIn) * 40}px)`,
            }}
          >
            <StepCircle n={i + 1} active={active} doneP={doneP} />
            <div style={{minWidth: 0}}>
              <div
                style={{
                  fontWeight: 800,
                  fontSize: 30,
                  color: doneP > 0.5 ? C.WHITE : active ? C.WHITE : '#d5d8dd',
                  whiteSpace: 'nowrap',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                }}
              >
                {it.icon ? (
                  <Img
                    src={staticFile(it.icon)}
                    style={{height: 30, filter: 'drop-shadow(0 2px 6px rgba(0,0,0,0.5))'}}
                  />
                ) : null}
                {it.title}
              </div>
              <div style={{fontWeight: 400, fontSize: 21, color: C.MUTED, marginTop: 2, whiteSpace: 'nowrap'}}>
                {it.sub}
              </div>
            </div>
          </div>
        );
      })}
      <div
        style={{height: 10, borderRadius: 5, background: 'rgba(255,255,255,0.08)', marginTop: 20, overflow: 'hidden'}}
      >
        <div
          style={{
            height: '100%',
            width: `${progress * 100}%`,
            borderRadius: 5,
            background: `linear-gradient(90deg, ${C.ORANGE}, #ffb347)`,
            boxShadow: '0 0 14px rgba(255,128,8,0.6)',
          }}
        />
      </div>
      <div style={{fontSize: 19, color: C.MUTED, marginTop: 10, textAlign: 'right'}}>
        {done} of {shown.length} done
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ root */

export const LessonOverlay: React.FC<OverlayProps> = ({intro, cards, sidebar, preview, sidebarAway}) => (
  <AbsoluteFill style={{backgroundColor: 'transparent'}}>
    {preview ? (
      <Img src={staticFile(preview)} style={{position: 'absolute', inset: 0, width: '100%', height: '100%'}} />
    ) : null}
    {intro ? <IntroBackground until={intro.until} /> : null}
    {cards.map((c, i) => (
      <IntroCard key={i} card={c} />
    ))}
    {sidebar ? <Sidebar sidebar={sidebar} away={sidebarAway} /> : null}
  </AbsoluteFill>
);

export const overlayDefaults: OverlayProps = {duration: 10, cards: []};
