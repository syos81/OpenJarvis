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
        println!("cargo:rustc-link-lib=framework=Contacts");
        println!("cargo:rustc-link-lib=framework=AppKit");
        println!("cargo:rustc-link-lib=framework=Foundation");
    }
    tauri_build::build();
}
