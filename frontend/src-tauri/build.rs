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
        // Produktiver Create im App-Prozess (ADR-0020 §8.1, Phase B).
        // Der Sidecar hat seit ADR-0020 keinen Schreibpfad mehr; der eine
        // CNSaveRequest lebt hier, wo der TCC-Grant und ein funktionierender
        // Store-Coordinator sind.
        cc::Build::new()
            .file("objc/JCContactsCreate.m")
            .flag("-fobjc-arc")
            .flag("-fmodules")
            .compile("jc_contacts_create");
        println!("cargo:rerun-if-changed=objc/JCContactsCreate.m");
        println!("cargo:rerun-if-changed=objc/JCContactsCreate.h");
        println!("cargo:rustc-link-lib=framework=Contacts");
        println!("cargo:rustc-link-lib=framework=AppKit");
        println!("cargo:rustc-link-lib=framework=Foundation");
    }
    tauri_build::build();
}
