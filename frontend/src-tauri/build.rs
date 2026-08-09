fn main() {
    // Der Kontakte-Berechtigungsdialog wird aus dem App-Prozess ausgeloest.
    // Der eigentliche Systemaufruf liegt in einem kleinen Objective-C-Shim
    // (objc/JCContactsAuthorization.m): dort prueft der Compiler Blocksignatur,
    // BOOL-Darstellung und Enum-Wert gegen die echten SDK-Header, und ARC
    // traegt die Lebensdauer von Block und Zustandsbox. Aus Rust waere all das
    // implizit geblieben.
    #[cfg(target_os = "macos")]
    {
        cc::Build::new()
            .file("objc/JCContactsAuthorization.m")
            .flag("-fobjc-arc")
            .flag("-fmodules")
            .compile("jc_contacts_authorization");
        println!("cargo:rerun-if-changed=objc/JCContactsAuthorization.m");
        println!("cargo:rerun-if-changed=objc/JCContactsAuthorization.h");
        // Produktiver Create im App-Prozess (ADR-0026 §8.1, Phase B).
        // Der Sidecar hat seit ADR-0026 keinen Schreibpfad mehr; der eine
        // CNSaveRequest lebt hier, wo der TCC-Grant und ein funktionierender
        // Store-Coordinator sind.
        cc::Build::new()
            .file("objc/JCContactsCreate.m")
            .flag("-fobjc-arc")
            .flag("-fmodules")
            .compile("jc_contacts_create");
        println!("cargo:rerun-if-changed=objc/JCContactsCreate.m");
        println!("cargo:rerun-if-changed=objc/JCContactsCreate.h");
        // Kalender-Schreibadapter (Block B3, P1 create): derselbe Schnitt wie
        // beim Kontakte-Create — der eine EventKit-Save lebt im App-Prozess
        // mit TCC-Grant, der Lese-Sidecar bleibt reiner Leser.
        cc::Build::new()
            .file("objc/JCCalendarWrite.m")
            .flag("-fobjc-arc")
            .flag("-fmodules")
            .compile("jc_calendar_write");
        println!("cargo:rerun-if-changed=objc/JCCalendarWrite.m");
        println!("cargo:rerun-if-changed=objc/JCCalendarWrite.h");
        println!("cargo:rustc-link-lib=framework=EventKit");
        println!("cargo:rustc-link-lib=framework=Contacts");
        println!("cargo:rustc-link-lib=framework=AppKit");
        println!("cargo:rustc-link-lib=framework=Foundation");
    }
    tauri_build::build();
}
