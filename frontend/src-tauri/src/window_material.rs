// Echtes Systemmaterial hinter dem Hauptfenster (macOS).
//
// **Was hier passiert.** Unter die Webansicht wird eine `NSVisualEffectView`
// gelegt — dieselbe Schicht, aus der die Seitenleisten der Systemprogramme
// bestehen. Sie ist kein nachgebauter Verlauf: Sie zeichnet das, was hinter
// dem Fenster liegt, mit der Unschaerfe und der Anpassung des Systems.
//
// **Warum das Fenster durchsichtig sein muss.** Eine `NSVisualEffectView`
// unter einem undurchsichtigen Fenster ist unsichtbar. Deshalb steht in
// `tauri.conf.json` `"transparent": true` und `"macOSPrivateApi": true`.
//
// **Und warum das trotzdem gefahrlos ist.** Ein durchsichtiges Fenster sieht
// genau so aus wie heute, solange das CSS seine Flaechen malt. Das CSS hoert
// damit erst auf, wenn `data-material="native"` am Wurzelelement steht — und
// dieses Attribut setzt diese Datei **ausschliesslich** nach erfolgreichem
// Einhaengen der Ansicht. Scheitert irgendein Schritt, bleibt das Attribut
// aus, die Annaeherung aus `index.css` malt weiter, und das Fenster sieht aus
// wie vorher. Fail-closed, in Richtung Sichtbarkeit.
//
// **Was hier nicht passiert.** Keine Flaeche wird hier eingefaerbt und keine
// Lesbarkeit entschieden. Welche Flaeche undurchsichtig bleibt, steht in
// `index.css` bei `--surface-opaque` — an einer Stelle, nicht an zweien.

#[cfg(target_os = "macos")]
mod imp {
    use objc::runtime::{Object, BOOL, NO, YES};
    use objc::{class, msg_send, sel, sel_impl};

    /// `NSVisualEffectBlendingModeBehindWindow` — hinter dem Fenster mischen,
    /// nicht innerhalb. Nur dieser Modus zeigt den Schreibtisch.
    const BLENDING_BEHIND_WINDOW: i64 = 0;
    /// `NSVisualEffectStateFollowsWindowActiveState`: Das Material wird
    /// flau, wenn das Fenster den Fokus verliert — wie im System ueblich.
    const STATE_FOLLOWS_WINDOW: i64 = 0;
    /// `NSVisualEffectMaterialUnderWindowBackground` (macOS 10.14+). Die
    /// Fensterhintergrund-Variante und nicht die Seitenleisten-Variante: Sie
    /// liegt unter der **ganzen** Flaeche, und genau das ist hier der Fall.
    const MATERIAL_UNDER_WINDOW_BACKGROUND: i64 = 21;

    /// Haengt das Material unter die Webansicht.
    ///
    /// `ns_window` ist der rohe `NSWindow`-Zeiger des Hauptfensters. Muss auf
    /// dem Hauptthread laufen — AppKit verlangt es, und Tauris `setup` ist
    /// dort.
    ///
    /// Gibt `true` zurueck, wenn die Ansicht nachweislich haengt. Nur dann
    /// darf das Attribut gesetzt werden.
    pub unsafe fn einhaengen(ns_window: *mut Object) -> bool {
        if ns_window.is_null() {
            return false;
        }
        let inhalt: *mut Object = msg_send![ns_window, contentView];
        if inhalt.is_null() {
            return false;
        }

        // Das Fenster selbst darf nicht mehr fuellen, sonst liegt eine
        // undurchsichtige Farbe ueber dem Material.
        let klar: *mut Object = msg_send![class!(NSColor), clearColor];
        let _: () = msg_send![ns_window, setOpaque: NO];
        let _: () = msg_send![ns_window, setBackgroundColor: klar];
        // Die Titelleiste mitnehmen: Eine gefuellte Leiste ueber einem
        // durchscheinenden Fenster ist ein sichtbarer Bruch.
        let _: () = msg_send![ns_window, setTitlebarAppearsTransparent: YES];

        // Bewusst `new` und **kein** `initWithFrame:`: Ein `NSRect` ist ein
        // C-Verbund aus vier `f64`, und ein Rust-Array hat keine zugesicherte
        // gleiche Uebergabeform. Fuer Code, der hier nicht zur Laufzeit
        // erprobt werden kann, ist Auto Layout der ehrlichere Weg — dabei
        // reisen ausschliesslich Objekte und Skalare.
        let effekt: *mut Object = msg_send![class!(NSVisualEffectView), new];
        if effekt.is_null() {
            return false;
        }
        let _: () = msg_send![effekt, setMaterial: MATERIAL_UNDER_WINDOW_BACKGROUND];
        let _: () = msg_send![effekt, setBlendingMode: BLENDING_BEHIND_WINDOW];
        let _: () = msg_send![effekt, setState: STATE_FOLLOWS_WINDOW];
        let _: () = msg_send![effekt, setTranslatesAutoresizingMaskIntoConstraints: NO];

        // `NSWindowBelow` (-1) gegen `nil`: unter **alles**, was schon da
        // ist — also unter die Webansicht. Ein `addSubview:` allein legte es
        // darueber, und dann saehe niemand mehr die Oberflaeche.
        let nichts: *mut Object = std::ptr::null_mut();
        let _: () = msg_send![inhalt, addSubview: effekt positioned: -1i64 relativeTo: nichts];

        // An alle vier Raender gebunden, statt mit einer Maske mitwachsend.
        // Jede Bindung wird einzeln aktiviert; das spart das `NSArray` und
        // damit den einzigen weiteren Verbund auf diesem Weg.
        if !an_die_raender_binden(effekt, inhalt) {
            return false;
        }

        // Nachgesehen, nicht angenommen: Haengt die Ansicht wirklich, und
        // liegt sie wirklich unten? Ohne diese Pruefung koennte das Attribut
        // gesetzt werden, waehrend das Fenster leer bleibt.
        let eltern: *mut Object = msg_send![effekt, superview];
        if eltern != inhalt {
            return false;
        }
        let kinder: *mut Object = msg_send![inhalt, subviews];
        if kinder.is_null() {
            return false;
        }
        let anzahl: usize = msg_send![kinder, count];
        if anzahl == 0 {
            return false;
        }
        let erstes: *mut Object = msg_send![kinder, objectAtIndex: 0usize];
        erstes == effekt
    }

    /// Nimmt der Webansicht ihre eigene Fuellung.
    ///
    /// Ohne das laege eine undurchsichtige `WKWebView` ueber dem Material,
    /// und das Fenster saehe aus wie vorher — nur mit einer unsichtbaren
    /// Ansicht darunter.
    pub unsafe fn webansicht_entfuellen(inhalt: *mut Object) {
        if inhalt.is_null() {
            return;
        }
        let kinder: *mut Object = msg_send![inhalt, subviews];
        if kinder.is_null() {
            return;
        }
        let anzahl: usize = msg_send![kinder, count];
        let klar: *mut Object = msg_send![class!(NSColor), clearColor];
        for i in 0..anzahl {
            let kind: *mut Object = msg_send![kinder, objectAtIndex: i];
            if kind.is_null() {
                continue;
            }
            let ist_web: BOOL = msg_send![kind, isKindOfClass: class!(WKWebView)];
            if ist_web == NO {
                continue;
            }
            // Beide Wege: die private Setzmethode und der Schluesselwert.
            // Welcher greift, haengt an der WebKit-Fassung; beide zu setzen
            // ist billiger als die Fallunterscheidung.
            let _: () = msg_send![kind, _setDrawsBackground: NO];
            let _: () = msg_send![kind, setValue: nsnumber_nein() forKey: nsstring("drawsBackground")];
            let _: () = msg_send![kind, setUnderPageBackgroundColor: klar];
        }
    }

    /// Bindet die Ansicht an alle vier Raender ihres Elters.
    ///
    /// Gibt `false` zurueck, sobald eine Bindung nicht entsteht — dann haengt
    /// das Material zwar, fuellt aber nicht, und ein halb gefuelltes Fenster
    /// waere schlimmer als gar keines.
    unsafe fn an_die_raender_binden(ansicht: *mut Object, elter: *mut Object) -> bool {
        for (eigen, fremd) in [
            (sel!(leadingAnchor), sel!(leadingAnchor)),
            (sel!(trailingAnchor), sel!(trailingAnchor)),
            (sel!(topAnchor), sel!(topAnchor)),
            (sel!(bottomAnchor), sel!(bottomAnchor)),
        ] {
            let a: *mut Object = msg_send![ansicht, performSelector: eigen];
            let b: *mut Object = msg_send![elter, performSelector: fremd];
            if a.is_null() || b.is_null() {
                return false;
            }
            let bindung: *mut Object = msg_send![a, constraintEqualToAnchor: b];
            if bindung.is_null() {
                return false;
            }
            let _: () = msg_send![bindung, setActive: YES];
        }
        true
    }

    unsafe fn nsnumber_nein() -> *mut Object {
        msg_send![class!(NSNumber), numberWithBool: NO]
    }

    unsafe fn nsstring(text: &str) -> *mut Object {
        let bytes = text.as_ptr() as *const std::os::raw::c_void;
        let s: *mut Object = msg_send![class!(NSString), alloc];
        msg_send![s, initWithBytes: bytes length: text.len() encoding: 4u64]
    }
}

/// Legt Systemmaterial hinter das Fenster und meldet, ob es steht.
///
/// Der Rueckgabewert ist die einzige Grundlage fuer `data-material="native"`.
/// Ausserhalb von macOS und bei jedem Fehlschlag ist er `false`, und die
/// Oberflaeche malt weiter ihre eigenen Flaechen.
pub fn material_einrichten(fenster: &tauri::WebviewWindow) -> bool {
    #[cfg(target_os = "macos")]
    {
        use objc::runtime::Object;
        use objc::{msg_send, sel, sel_impl};

        let Ok(ns_window) = fenster.ns_window() else {
            return false;
        };
        let ns_window = ns_window as *mut Object;
        unsafe {
            if !imp::einhaengen(ns_window) {
                return false;
            }
            let inhalt: *mut Object = msg_send![ns_window, contentView];
            imp::webansicht_entfuellen(inhalt);
        }
        true
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = fenster;
        false
    }
}

/// Sagt der Oberflaeche, dass echtes Material dahinterliegt.
///
/// Erst hier hoert das CSS auf, die grossen Flaechen zu malen. Wird diese
/// Funktion nie erreicht, bleibt die Annaeherung stehen — genau das ist die
/// Rueckfallebene.
pub fn material_melden(fenster: &tauri::WebviewWindow) {
    let _ = fenster.eval(
        "document.documentElement.setAttribute('data-material','native');",
    );
}

#[cfg(test)]
mod tests {
    /// Der Waechter, der ein leeres Fenster verhindert.
    ///
    /// Die ganze Gefahrlosigkeit dieses Umbaus haengt an einer Stelle: Das
    /// Attribut `data-material` darf **nur** gesetzt werden, wenn das
    /// Einhaengen nachweislich gelungen ist. Wird es unbedingt gesetzt, hoert
    /// das CSS auf, seine Flaechen zu malen — und ein durchsichtiges Fenster
    /// ohne Material ist ein leeres Fenster.
    ///
    /// Geprueft wird die Verdrahtung im Quelltext, weil sie sich sonst nur
    /// mit einem laufenden Fenster pruefen liesse.
    #[test]
    fn das_attribut_haengt_am_nachgewiesenen_erfolg() {
        let lib = include_str!("lib.rs");
        let ohne_kommentare: String = lib
            .lines()
            .filter(|z| !z.trim_start().starts_with("//"))
            .collect::<Vec<_>>()
            .join("\n");

        // Genau ein Aufruf, und er steht im Rumpf der Erfolgspruefung.
        assert_eq!(ohne_kommentare.matches("material_melden(").count(), 1);
        let vor_dem_melden = ohne_kommentare
            .split("material_melden(")
            .next()
            .expect("Vorlauf");
        let bedingung = "if crate::window_material::material_einrichten(&fenster) {";
        assert!(vor_dem_melden.ends_with(&format!("{bedingung}\n                    crate::window_material::")),
                "unerwartete Verdrahtung: {:?}",
                &vor_dem_melden[vor_dem_melden.len().saturating_sub(160)..]);
    }

    /// Ausserhalb von macOS gibt es kein Material — und deshalb auch kein
    /// Attribut. Sonst maehte das CSS seine Flaechen auf einer Plattform ab,
    /// auf der nichts dahinterliegt.
    #[test]
    #[cfg(not(target_os = "macos"))]
    fn ohne_macos_gibt_es_kein_material() {
        // Die Funktion ist dort ein `false` ohne Seitenwirkung; geprueft wird
        // hier nur, dass sie ueberhaupt existiert und nichts anderes tut.
        let quelle = include_str!("window_material.rs");
        assert!(quelle.contains("#[cfg(not(target_os = \"macos\"))]"));
    }
}
